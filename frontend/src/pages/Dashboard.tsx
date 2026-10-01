import { motion } from "framer-motion";
import { Users, Phone, AtSign, Database, Search } from "lucide-react";

const STATS = [
  { icon: Users, label: "Faces", value: "0" },
  { icon: Phone, label: "Phones", value: "0" },
  { icon: AtSign, label: "Emails", value: "0" },
  { icon: Database, label: "Sources", value: "0" },
];

export function Dashboard() {
  return (
    <>
      {/* Universal search bar (wired in Phase 3) */}
      <div className="mb-6 flex items-center gap-2 rounded-lg border border-line bg-panel px-4 py-3">
        <Search size={16} className="text-muted" />
        <input
          disabled
          placeholder="Search phone / email / username / domain  (available in Phase 3)"
          className="w-full bg-transparent text-sm outline-none placeholder:text-muted"
        />
      </div>

      {/* Stat tiles */}
      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        {STATS.map(({ icon: Icon, label, value }, i) => (
          <motion.div
            key={label}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.05 }}
            className="rounded-lg border border-line bg-panel p-4"
          >
            <div className="flex items-center justify-between">
              <span className="kai-metadata uppercase">{label}</span>
              <Icon size={15} className="text-muted" />
            </div>
            <div className="mt-2 font-mono text-2xl">{value}</div>
          </motion.div>
        ))}
      </div>

      {/* Map placeholder */}
      <div className="mb-6 flex h-64 items-center justify-center rounded-lg border border-line bg-panel-2">
        <span className="kai-metadata">LIVE INTELLIGENCE MAP — Phase 13</span>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-line bg-panel p-4">
          <div className="kai-metadata mb-3 uppercase">Recent Investigations</div>
          <div className="text-sm text-muted">No investigations yet.</div>
        </div>
        <div className="rounded-lg border border-line bg-panel p-4">
          <div className="kai-metadata mb-3 uppercase">Index Activity</div>
          <div className="text-sm text-muted">Indexing starts in Phase 9–10.</div>
        </div>
      </div>
    </>
  );
}
