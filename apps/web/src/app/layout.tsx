import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "RAG Eval Platform",
    template: "%s | RAG Eval Platform",
  },
  description: "可复现、可解释的 RAG 评测工作台。",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html data-theme="light" lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
