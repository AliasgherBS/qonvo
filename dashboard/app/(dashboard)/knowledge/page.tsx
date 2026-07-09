"use client";

import { BookOpen, FileUp, Globe, RefreshCw } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { knowledge, type KnowledgeSource, type KnowledgeSourceStatus } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<KnowledgeSourceStatus, "success" | "warning" | "danger" | "default"> = {
  ready: "success",
  processing: "warning",
  pending: "default",
  error: "danger",
};

export default function KnowledgePage() {
  const { data, loading, error, refetch } = useApi(() => knowledge.listSources());

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Knowledge</h1>
        <p className="text-sm text-muted-foreground">
          What your AI representative knows — upload docs, connect a website, or write it by hand.
        </p>
      </div>

      <UploadDropzone onUploaded={refetch} />

      <div className="overflow-hidden rounded-2xl border border-border bg-surface">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <h2 className="text-sm font-bold">Sources</h2>
          <Button variant="ghost" size="sm" onClick={refetch}>
            <RefreshCw className="h-4 w-4" />
            Refresh
          </Button>
        </div>

        <SourcesTable sources={data} loading={loading} error={error} onRetry={refetch} />
      </div>
    </div>
  );
}

function UploadDropzone({ onUploaded }: { onUploaded: () => void }) {
  const [isDragging, setIsDragging] = useState(false);
  const [status, setStatus] = useState<"idle" | "uploading" | "error">("idle");
  const inputRef = useRef<HTMLInputElement>(null);

  async function upload(file: File) {
    setStatus("uploading");
    try {
      await knowledge.uploadFile(file);
      onUploaded();
      setStatus("idle");
    } catch {
      setStatus("error");
    }
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) void upload(file);
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-colors",
        isDragging ? "border-primary bg-primary/5" : "border-border-strong hover:bg-surface-muted",
      )}
    >
      <input
        ref={inputRef}
        type="file"
        className="hidden"
        accept=".pdf,.docx,.csv"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void upload(file);
        }}
      />
      <FileUp className="h-6 w-6 text-muted-foreground" />
      <p className="text-sm font-semibold">
        {status === "uploading" ? "Uploading…" : "Drop a PDF, DOCX, or CSV here"}
      </p>
      <p className="text-xs text-muted-foreground">or click to browse — website crawling coming from Settings</p>
      {status === "error" ? (
        <p className="text-xs text-danger">Upload failed — the knowledge API isn&apos;t connected yet.</p>
      ) : null}
    </div>
  );
}

function SourcesTable({
  sources,
  loading,
  error,
  onRetry,
}: {
  sources: KnowledgeSource[] | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  if (loading) {
    return (
      <div className="space-y-3 p-5">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-5">
        <EmptyState
          icon={<BookOpen className="h-5 w-5" />}
          title="Can't reach the backend yet"
          description="Sources will list here once the knowledge API is connected."
          action={
            <Button variant="outline" size="sm" onClick={onRetry}>
              Retry
            </Button>
          }
        />
      </div>
    );
  }

  if (!sources || sources.length === 0) {
    return (
      <div className="p-5">
        <EmptyState
          icon={<Globe className="h-5 w-5" />}
          title="No knowledge sources yet"
          description="Upload a document or add a website above to start grounding replies."
        />
      </div>
    );
  }

  return (
    <table className="w-full text-sm">
      <thead className="text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
        <tr>
          <th className="px-5 py-3">Title</th>
          <th className="px-5 py-3">Type</th>
          <th className="px-5 py-3">Chunks</th>
          <th className="px-5 py-3">Status</th>
          <th className="px-5 py-3">Updated</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-border">
        {sources.map((source) => (
          <tr key={source.id}>
            <td className="px-5 py-3 font-semibold">{source.title}</td>
            <td className="px-5 py-3 capitalize text-muted-foreground">{source.type}</td>
            <td className="px-5 py-3 text-muted-foreground">{source.chunkCount}</td>
            <td className="px-5 py-3">
              <Badge tone={STATUS_TONE[source.status]}>{source.status}</Badge>
            </td>
            <td className="px-5 py-3 text-muted-foreground">
              {new Date(source.updatedAt).toLocaleDateString()}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
