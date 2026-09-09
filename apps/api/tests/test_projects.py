import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from rag_eval_api.models import (
    AuditEvent,
    Base,
    Membership,
    MembershipRole,
    Organization,
    Project,
)


@pytest.fixture
def db() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(
        dbapi_connection: sqlite3.Connection,
        connection_record: object,
    ) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_projects_and_memberships_are_isolated_by_organization(db: Session) -> None:
    first_organization = Organization(name="First Organization", slug="first")
    second_organization = Organization(name="Second Organization", slug="second")
    first_project = Project(name="First Project", slug="first", organization=first_organization)
    second_project = Project(name="Second Project", slug="second", organization=second_organization)
    users = [uuid4() for _ in range(3)]

    db.add_all(
        [
            first_organization,
            second_organization,
            first_project,
            second_project,
            Membership(
                organization=first_organization,
                project=first_project,
                user_id=users[0],
                role=MembershipRole.admin,
            ),
            Membership(
                organization=first_organization,
                project=first_project,
                user_id=users[1],
                role=MembershipRole.editor,
            ),
            Membership(
                organization=second_organization,
                project=second_project,
                user_id=users[2],
                role=MembershipRole.viewer,
            ),
        ]
    )
    db.commit()

    assert {project.slug for project in first_organization.projects} == {"first"}
    assert {project.slug for project in second_organization.projects} == {"second"}
    assert first_project.organization_id == first_organization.id
    assert second_project.organization_id == second_organization.id
    assert {membership.role for membership in first_project.memberships} == {
        MembershipRole.admin,
        MembershipRole.editor,
    }
    assert {membership.role for membership in second_project.memberships} == {MembershipRole.viewer}


def test_one_organization_keeps_memberships_isolated_between_two_projects(db: Session) -> None:
    organization = Organization(name="Organization", slug="organization")
    first_project = Project(name="First Project", slug="first", organization=organization)
    second_project = Project(name="Second Project", slug="second", organization=organization)
    admin_id = UUID("00000000-0000-0000-0000-000000000011")
    editor_id = UUID("00000000-0000-0000-0000-000000000012")
    viewer_id = UUID("00000000-0000-0000-0000-000000000013")
    db.add_all(
        [
            organization,
            first_project,
            second_project,
            Membership(
                organization=organization,
                project=first_project,
                user_id=admin_id,
                role=MembershipRole.admin,
            ),
            Membership(
                organization=organization,
                project=first_project,
                user_id=editor_id,
                role=MembershipRole.editor,
            ),
            Membership(
                organization=organization,
                project=second_project,
                user_id=viewer_id,
                role=MembershipRole.viewer,
            ),
        ]
    )
    db.commit()

    assert {project.slug for project in organization.projects} == {"first", "second"}
    assert {membership.role for membership in first_project.memberships} == {
        MembershipRole.admin,
        MembershipRole.editor,
    }
    assert {membership.role for membership in second_project.memberships} == {MembershipRole.viewer}
    assert {membership.user_id for membership in first_project.memberships} == {
        admin_id,
        editor_id,
    }
    assert {membership.user_id for membership in second_project.memberships} == {viewer_id}
    assert all(membership.project_id == first_project.id for membership in first_project.memberships)
    assert all(membership.project_id == second_project.id for membership in second_project.memberships)


def test_membership_cannot_pair_project_with_another_organization(db: Session) -> None:
    first_organization = Organization(name="First Organization", slug="first")
    second_organization = Organization(name="Second Organization", slug="second")
    first_project = Project(name="First Project", slug="first", organization=first_organization)
    second_project = Project(name="Second Project", slug="second", organization=second_organization)
    db.add_all([first_organization, second_organization, first_project, second_project])
    db.commit()

    db.add(
        Membership(
            organization_id=first_organization.id,
            project_id=second_project.id,
            user_id=uuid4(),
            role=MembershipRole.viewer,
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_membership_relationships_reject_mismatched_organization_and_project(
    db: Session,
) -> None:
    first_organization = Organization(name="First Organization", slug="first")
    second_organization = Organization(name="Second Organization", slug="second")
    first_project = Project(name="First Project", slug="first", organization=first_organization)
    second_project = Project(name="Second Project", slug="second", organization=second_organization)
    db.add_all([first_organization, second_organization, first_project, second_project])
    db.commit()

    db.add(
        Membership(
            organization=first_organization,
            project=second_project,
            user_id=uuid4(),
            role=MembershipRole.viewer,
        )
    )
    with pytest.raises(ValueError, match="organization and project must belong to the same tenant"):
        db.commit()
    db.rollback()


def test_membership_relationship_updates_reject_mismatched_tenant(db: Session) -> None:
    first_organization = Organization(name="First Organization", slug="first")
    second_organization = Organization(name="Second Organization", slug="second")
    first_project = Project(name="First Project", slug="first", organization=first_organization)
    second_project = Project(name="Second Project", slug="second", organization=second_organization)
    membership = Membership(
        organization=first_organization,
        project=first_project,
        user_id=uuid4(),
        role=MembershipRole.viewer,
    )
    db.add_all([first_organization, second_organization, first_project, second_project, membership])
    db.commit()

    membership.organization = second_organization
    membership.project = first_project
    with pytest.raises(ValueError, match="organization and project must belong to the same tenant"):
        db.commit()
    db.rollback()


def test_audit_event_cannot_pair_project_with_another_organization(db: Session) -> None:
    first_organization = Organization(name="First Organization", slug="first")
    second_organization = Organization(name="Second Organization", slug="second")
    first_project = Project(name="First Project", slug="first", organization=first_organization)
    second_project = Project(name="Second Project", slug="second", organization=second_organization)
    db.add_all([first_organization, second_organization, first_project, second_project])
    db.commit()

    db.add(
        AuditEvent(
            organization_id=first_organization.id,
            project_id=second_project.id,
            actor_id=uuid4(),
            action="project.created",
            resource_type="project",
            resource_id=str(second_project.id),
            metadata_json={},
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_audit_relationships_reject_mismatched_organization_and_project(db: Session) -> None:
    first_organization = Organization(name="First Organization", slug="first")
    second_organization = Organization(name="Second Organization", slug="second")
    first_project = Project(name="First Project", slug="first", organization=first_organization)
    second_project = Project(name="Second Project", slug="second", organization=second_organization)
    db.add_all([first_organization, second_organization, first_project, second_project])
    db.commit()

    db.add(
        AuditEvent(
            organization=first_organization,
            project=second_project,
            actor_id=uuid4(),
            action="project.created",
            resource_type="project",
            resource_id=str(second_project.id),
            metadata_json={},
        )
    )
    with pytest.raises(ValueError, match="organization and project must belong to the same tenant"):
        db.commit()
    db.rollback()


def test_project_slug_is_unique_within_an_organization_but_not_across_organizations(
    db: Session,
) -> None:
    first_organization = Organization(name="First Organization", slug="first")
    second_organization = Organization(name="Second Organization", slug="second")
    db.add_all(
        [
            first_organization,
            second_organization,
            Project(name="First Project", slug="shared", organization=first_organization),
            Project(name="Second Project", slug="shared", organization=second_organization),
        ]
    )
    db.commit()

    db.add(Project(name="Duplicate Project", slug="shared", organization=first_organization))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_membership_role_values_are_restricted_by_database_constraint(db: Session) -> None:
    organization = Organization(name="Organization", slug="organization")
    project = Project(name="Project", slug="project", organization=organization)
    db.add(
        Membership(
            organization=organization,
            project=project,
            user_id=uuid4(),
            role=cast(MembershipRole, "owner"),
        )
    )

    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_membership_is_unique_per_project_and_user(db: Session) -> None:
    organization = Organization(name="Organization", slug="organization")
    project = Project(name="Project", slug="project", organization=organization)
    user_id = uuid4()
    db.add(
        Membership(
            organization=organization,
            project=project,
            user_id=user_id,
            role=MembershipRole.editor,
        )
    )
    db.commit()

    db.add(
        Membership(
            organization=organization,
            project=project,
            user_id=user_id,
            role=MembershipRole.viewer,
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_audit_event_preserves_actor_timestamp_and_project_scope(db: Session) -> None:
    organization = Organization(name="Organization", slug="organization")
    project = Project(name="Project", slug="project", organization=organization)
    actor_id = UUID("00000000-0000-0000-0000-000000000001")
    db.add(
        AuditEvent(
            organization=organization,
            project=project,
            actor_id=actor_id,
            action="project.created",
            resource_type="project",
            resource_id=str(project.id),
            metadata_json={"source": "test"},
        )
    )
    db.commit()

    event = db.query(AuditEvent).one()
    assert event.actor_id == actor_id
    assert event.created_at is not None
    assert event.created_at.tzinfo is not None
    assert event.created_at.utcoffset() == UTC.utcoffset(event.created_at)
    assert event.project_id == project.id
    assert event.metadata_json == {"source": "test"}


def test_audit_event_update_and_delete_are_rejected_and_record_remains(db: Session) -> None:
    organization = Organization(name="Organization", slug="organization")
    project = Project(name="Project", slug="project", organization=organization)
    event = AuditEvent(
        organization=organization,
        project=project,
        actor_id=uuid4(),
        action="project.created",
        resource_type="project",
        resource_id=str(project.id),
        metadata_json={"source": "test"},
    )
    db.add(event)
    db.commit()
    event_id = event.id

    event.action = "project.deleted"
    with pytest.raises(ValueError, match="append-only"):
        db.commit()
    db.rollback()
    persisted_event = db.get(AuditEvent, event_id)
    assert persisted_event is not None
    assert persisted_event.action == "project.created"

    db.delete(persisted_event)
    with pytest.raises(ValueError, match="append-only"):
        db.commit()
    db.rollback()
    assert db.get(AuditEvent, event_id) is not None


def test_audit_event_created_at_uses_database_default() -> None:
    from rag_eval_api.models import AuditEvent

    server_default = AuditEvent.__table__.c.created_at.server_default

    assert server_default is not None
    assert str(server_default.arg) == "CURRENT_TIMESTAMP"


def test_timestamp_defaults_are_utc_aware(db: Session) -> None:
    organization = Organization(name="Organization", slug="organization")
    db.add(organization)
    db.commit()

    assert isinstance(organization.created_at, datetime)
    assert organization.created_at.tzinfo is not None
    assert organization.updated_at.tzinfo is not None
