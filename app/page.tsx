import { redirect } from "next/navigation";
import { access } from "@/lib/auth";
import { listJobs, listCompanies } from "@/lib/db";
import Dashboard from "@/components/dashboard";
export const dynamic = "force-dynamic";
export default async function Page() {
  const mode = await access();
  if (!mode) redirect("/login");
  return <Dashboard jobs={listJobs()} companies={listCompanies()} local={mode === "local"} />;
}
