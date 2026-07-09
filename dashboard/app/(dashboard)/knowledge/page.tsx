"use client";

import { BookOpen, FileUp, HelpCircle, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useRef, useState, type DragEvent, type FormEvent } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { knowledge, type KnowledgeGap, type KnowledgeSource, type KnowledgeSourceStatus } from "@/lib/api";
import { useApi, useAuthToken } from "@/lib/use-api";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<KnowledgeSourceStatus, "success" | "warning" | "danger" | "default"> = {
  ready: "success",
  processing: "warning",
  pending: "default",
  error: "danger",
};

type Tab = "sources" | "gaps";

export default function KnowledgePage() {
  const token = useAuthToken();
  const { toast } = useToast();
  const [tab, setTab] = useState<Tab>("sources");
  const [manualOpen, setManualOpen] = useState(false);

  const { data, loading, error, refetch } = useApi(() => knowledge.listSources({ token }), [token]);
  const {
    data: gaps,
    loading: gapsLoading,
    error: gapsError,
    refetch: refetchGaps,
  } = useApi(() => knowledge.gaps({ token }), [token]);

  async function handleDelete(source: KnowledgeSource) {
    if (!window.confirm(`Delete "${source.title}"? This can't be undone.`)) return;
    try {
      await knowledge.deleteSource(source.id, { token });
      toast({ title: "Source deleted", variant: "success" });
      refetch();
    } catch {
      toast({ title: "Couldn't delete source", description: "The knowledge API isn't connected yet.", variant: "error" });
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight">Knowledge</h1>
          <p className="text-sm text-muted-foreground">
            What your AI representative knows — upload docs, write entries by hand, or review the gaps.
          </p>
        </div>
        <Button onClick={() => setManualOpen(true)}>
          <Plus className="h-4 w-4" />
          Add entry
        </Button>
      </div>

      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => setTab("sources")}
          className={cn(
            "rounded-full px-4 py-1.5 text-sm font-semibold transition-colors",
            tab === "sources" ? "bg-primary text-primary-foreground" : "bg-surface-muted hover:bg-border",
          )}
        >
          Sources
        </button>
        <button
          type="button"
          onClick={() => setTab("gaps")}
          className={cn(
            "rounded-full px-4 py-1.5 text-sm font-semibold transition-colors",
            tab === "gaps" ? "bg-primary text-primary-foreground" : "bg-surface-muted hover:bg-border",
          )}
        >
          Gaps
        </button>
      </div>

      {tab === "sources" ? (
        <>
          <UploadDropzone onUploaded={refetch} />

          <div className="overflow-hidden rounded-2xl border border-border bg-surface">
            <div className="flex items-center justify-between border-b border-border px-5 py-4">
              <h2 className="text-sm font-bold">Sources</h2>
              <Button variant="ghost" size="sm" onClick={refetch}>
                <RefreshCw className="h-4 w-4" />
                Refresh
              </Button>
            </div>

            <SourcesTable sources={data} loading={loading} error={error} onRetry={refetch} onDelete={handleDelete} />
          </div>
        </>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-border bg-surface">
          <div className="flex items-center justify-between border-b border-border px-5 py-4">
            <h2 className="text-sm font-bold">Questions the bot couldn&apos;t answer</h2>
            <Button variant="ghost" size="sm" onClick={refetchGaps}>
              <RefreshCw className="h-4 w-4" />
              Refresh
            </Button>
          </div>
          <GapsTable gaps={gaps} loading={gapsLoading} error={gapsError} onRetry={refetchGaps} />
        </div>
      )}

      <AddManualEntryDialog
        open={manualOpen}
        onClose={() => setManualOpen(false)}
        onCreated={() => {
          setManualOpen(false);
          refetch();
        }}
      />
    </div>
  );
}

function AddManualEntryDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const token = useAuthToken();
  const { toast } = useToast();
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [saving, setSaving] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!title.trim() || !content.trim()) return;
    setSaving(true);
    try {
      await knowledge.addManualEntry({ title: title.trim(), content: content.trim() }, { token });
      toast({ title: "Entry added", variant: "success" });
      setTitle("");
      setContent("");
      onCreated();
    } catch {
      toast({ title: "Couldn't add entry", description: "The knowledge API isn't connected yet.", variant: "error" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title="Add a manual entry" description="Write a fact or answer by hand.">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="entry-title">Title</Label>
          <Input
            id="entry-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Refund policy"
            required
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="entry-content">Content</Label>
          <Textarea
            id="entry-content"
            rows={5}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="What should the AI rep know?"
            required
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={saving}>
            {saving ? "Adding…" : "Add entry"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function UploadDropzone({ onUploaded }: { onUploaded: () => void }) {
  const token = useAuthToken();
  const { toast } = useToast();
  const [isDragging, setIsDragging] = useState(false);
  const [status, setStatus] = useState<"idle" | "uploading" | "error">("idle");
  const inputRef = useRef<HTMLInputElement>(null);

  async function upload(file: File) {
    setStatus("uploading");
    try {
      const source = await knowledge.createFileSource(file.name, { token });
      await knowledge.uploadFile(source.id, file, { token });
      toast({ title: "File uploaded", description: file.name, variant: "success" });
      onUploaded();
      setStatus("idle");
    } catch {
      setStatus("error");
      toast({ title: "Upload failed", description: "The knowledge API isn't connected yet.", variant: "error" });
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
      <p className="text-xs text-muted-foreground">or click to browse</p>
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
  onDelete,
}: {
  sources: KnowledgeSource[] | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onDelete: (source: KnowledgeSource) => void;
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
          icon={<BookOpen className="h-5 w-5" />}
          title="No knowledge sources yet"
          description="Upload a document or add a manual entry above to start grounding replies."
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
          <th className="px-5 py-3">Status</th>
          <th className="px-5 py-3">Updated</th>
          <th className="px-5 py-3" />
        </tr>
      </thead>
      <tbody className="divide-y divide-border">
        {sources.map((source) => (
          <tr key={source.id}>
            <td className="px-5 py-3 font-semibold">{source.title}</td>
            <td className="px-5 py-3 capitalize text-muted-foreground">{source.type}</td>
            <td className="px-5 py-3">
              <Badge tone={STATUS_TONE[source.status]}>{source.status}</Badge>
            </td>
            <td className="px-5 py-3 text-muted-foreground">
              {source.updatedAt ? new Date(source.updatedAt).toLocaleDateString() : "—"}
            </td>
            <td className="px-5 py-3 text-right">
              <Button variant="ghost" size="sm" onClick={() => onDelete(source)} aria-label={`Delete ${source.title}`}>
                <Trash2 className="h-4 w-4" />
              </Button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function GapsTable({
  gaps,
  loading,
  error,
  onRetry,
}: {
  gaps: KnowledgeGap[] | null;
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
          icon={<HelpCircle className="h-5 w-5" />}
          title="Can't reach the backend yet"
          description="Unanswered questions will list here once the knowledge API is connected."
          action={
            <Button variant="outline" size="sm" onClick={onRetry}>
              Retry
            </Button>
          }
        />
      </div>
    );
  }

  if (!gaps || gaps.length === 0) {
    return (
      <div className="p-5">
        <EmptyState
          icon={<HelpCircle className="h-5 w-5" />}
          title="No gaps yet"
          description="Questions your AI rep couldn't answer will show up here so you can fill the gap."
        />
      </div>
    );
  }

  return (
    <table className="w-full text-sm">
      <thead className="text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
        <tr>
          <th className="px-5 py-3">Question</th>
          <th className="px-5 py-3">Times asked</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-border">
        {gaps.map((gap) => (
          <tr key={gap.id}>
            <td className="px-5 py-3 font-semibold">{gap.question}</td>
            <td className="px-5 py-3 text-muted-foreground">{gap.count}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
