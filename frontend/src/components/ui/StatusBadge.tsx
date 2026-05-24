import { CircleCheck, Clock3, TriangleAlert } from "lucide-react";
import type { DocumentStatus } from "../../types";

const statusMeta = {
  ready: { label: "Ready", icon: CircleCheck },
  processing: { label: "Processing", icon: Clock3 },
  failed: { label: "Failed", icon: TriangleAlert }
};

export function StatusBadge({ status }: { status: DocumentStatus }) {
  const meta = statusMeta[status];
  const Icon = meta.icon;

  return (
    <span className={`status-badge status-${status}`}>
      <Icon size={14} />
      {meta.label}
    </span>
  );
}
