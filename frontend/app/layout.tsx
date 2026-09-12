import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "GoalForge AI", description: "Adaptive multi-agent goal planning" };
export default function Layout({ children }: { children: React.ReactNode }) { return <html lang="en"><body>{children}</body></html>; }
