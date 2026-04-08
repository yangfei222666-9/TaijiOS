import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TaijiOS Demo",
  description: "Task execution demo for TaijiOS",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh">
      <body>{children}</body>
    </html>
  );
}
