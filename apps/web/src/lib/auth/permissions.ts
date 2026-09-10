export const userRoles = ["admin", "editor", "viewer"] as const;

export type UserRole = (typeof userRoles)[number];

export const permissions = [
  "project.read",
  "asset.read",
  "asset.edit",
  "adapter.edit",
  "experiment.read",
  "experiment.edit",
  "diagnostics.read",
  "service.admin",
  "member.admin",
] as const;

export type Permission = (typeof permissions)[number];

/**
 * Development web roles are explicit until the authentication boundary is
 * connected. This map is the single source of truth for route visibility.
 */
export const rolePermissions: Record<UserRole, readonly Permission[]> = {
  admin: permissions,
  editor: [
    "project.read",
    "asset.read",
    "asset.edit",
    "adapter.edit",
    "experiment.read",
    "experiment.edit",
    "diagnostics.read",
    "service.admin",
  ],
  viewer: ["project.read", "asset.read", "experiment.read", "diagnostics.read"],
};

export function hasPermission(role: UserRole, permission: Permission): boolean {
  return rolePermissions[role].includes(permission);
}
