import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "太极OS 演示",
  description: "太极OS 任务执行引擎演示",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh">
      <body>{children}</body>
    </html>
  );
}
