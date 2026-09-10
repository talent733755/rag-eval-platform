"use client";

import Link, { type LinkProps } from "next/link";
import type { AnchorHTMLAttributes, ReactNode } from "react";

import { preserveProjectQuery, useProjectSearch } from "../../lib/project-context";

type ProjectLinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> &
  Pick<LinkProps, "replace" | "scroll" | "shallow" | "prefetch" | "passHref"> & {
    href: string;
    children: ReactNode;
  };

export function ProjectLink({ children, href, ...props }: ProjectLinkProps) {
  const search = useProjectSearch();

  return (
    <Link {...props} href={preserveProjectQuery(href, search)}>
      {children}
    </Link>
  );
}
