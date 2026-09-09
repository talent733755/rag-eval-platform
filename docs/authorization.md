# Authorization foundation policy

The foundation schema currently has project memberships but no separate
`organization_memberships` table. Until organization-level memberships are
introduced, the API treats an actor with an `admin` membership in any project
of an organization as an organization administrator. This is an explicit
temporary policy, not an implicit trust of client-supplied organization IDs.

All authorization queries scope the authenticated actor by both `user_id` and
`organization_id`. Project member mutations recheck the actor membership and
lock project membership rows in the same transaction where the database
supports `FOR UPDATE`. SQLite ignores those row locks; SQLite tests therefore
cover authorization state and transaction atomicity, while PostgreSQL is the
production concurrency authority.
