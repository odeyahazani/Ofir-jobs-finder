import { redirect } from "next/navigation";
import { access } from "@/lib/auth";
import { listJobs, listCompanies, listDiscoveries } from "@/lib/db";
import Dashboard from "@/components/dashboard";
export const dynamic = "force-dynamic";
export default async function Page() {
  const mode = await access();
  if (!mode) redirect("/login");
  const [jobs, companies, discoveries] = await Promise.all([listJobs(), listCompanies(), listDiscoveries()]);
  return <Dashboard jobs={jobs} companies={companies} discoveries={discoveries.items} importReady={discoveries.available} local={mode === "local"} />;
}
