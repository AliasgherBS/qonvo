"use client";

import { BookOpen, FileUp, HelpCircle, Pencil, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useRef, useState, type DragEvent, type FormEvent } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import {
  describeError,
  knowledge,
  type KnowledgeGap,
  type KnowledgeSource,
  type KnowledgeSourceStatus,
} from "@/lib/api";
import { useApi, useAuthToken } from "@/lib/use-api";
import { cn } from "@/lib/utils";

// Backend emits "pending_ingest" | "ready" | "error"; fall back gracefully so a
// new/unknown status never renders as a blank badge.
function statusTone(status: KnowledgeSourceStatus): "success" | "warning" | "danger" | "default" {
  if (status === "ready") return "success";
  if (status === "error") return "danger";
  if (status === "pending_ingest") return "warning";
  return "default";
}

function statusLabel(status: KnowledgeSourceStatus): string {
  if (status === "pending_ingest") return "Processing";
  if (status === "ready") return "Ready";
  if (status === "error") return "Error";
  return status;
}

type Tab = "sources" | "gaps";

export default function KnowledgePage() {
  const token = useAuthToken();
  const { toast } = useToast();
  const [tab, setTab] = useState<Tab>("sources");
  const [manualOpen, setManualOpen] = useState(false);
  const [editing, setEditing] = useState<KnowledgeSource | null>(null);

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
    } catch (err) {
      toast({ title: "Couldn't delete source", description: describeError(err), variant: "error" });
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

            <SourcesTable
              sources={data}
              loading={loading}
              error={error}
              onRetry={refetch}
              onDelete={handleDelete}
              onView={setEditing}
            />
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

      <ViewEditSourceDialog
        source={editing}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          refetch();
        }}
      />
    </div>
  );
}

function ViewEditSourceDialog({
  source,
  onClose,
  onSaved,
}: {
  source: KnowledgeSource | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const token = useAuthToken();
  const { toast } = useToast();
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  // Manual entries are edited inline; files/URLs are ingested from their upload
  // so their extracted text is shown read-only (editing it wouldn't round-trip).
  const editable = source?.type === "manual";

  useEffect(() => {
    if (!source) return;
    setTitle(source.title);
    setContent(source.content ?? "");
    // The list payload already carries content, but re-fetch to be sure it's the
    // freshest copy (and to fill it if a future list omits it).
    if (source.content == null) {
      setLoading(true);
      knowledge
        .getSource(source.id, { token })
        .then((full) => setContent(full.content ?? ""))
        .catch(() => setContent(""))
        .finally(() => setLoading(false));
    }
  }, [source, token]);

  async function handleSave() {
    if (!source) return;
    setSaving(true);
    try {
      await knowledge.updateSource(source.id, { title: title.trim(), content: content.trim() }, { token });
      toast({ title: "Entry updated", variant: "success" });
      onSaved();
    } catch {
      toast({ title: "Couldn't update entry", variant: "error" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open={source !== null}
      onClose={onClose}
      title={editable ? "Edit entry" : "View source"}
      description={editable ? "Update the title or content — saving re-indexes it." : "Extracted content (read-only)."}
    >
      <div className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="edit-title">Title</Label>
          <Input id="edit-title" value={title} onChange={(e) => setTitle(e.target.value)} disabled={!editable} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="edit-content">Content</Label>
          <Textarea
            id="edit-content"
            rows={8}
            value={loading ? "Loading…" : content}
            onChange={(e) => setContent(e.target.value)}
            disabled={!editable || loading}
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose}>
            Close
          </Button>
          {editable ? (
            <Button type="button" onClick={handleSave} disabled={saving || !title.trim()}>
              {saving ? "Saving…" : "Save changes"}
            </Button>
          ) : null}
        </div>
      </div>
    </Dialog>
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
    } catch (err) {
      toast({ title: "Couldn't add entry", description: describeError(err), variant: "error" });
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
    } catch (err) {
      setStatus("error");
      toast({ title: "Upload failed", description: describeError(err), variant: "error" });
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
        <p className="text-xs text-danger">Upload failed — please try again.</p>
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
  onView,
}: {
  sources: KnowledgeSource[] | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onDelete: (source: KnowledgeSource) => void;
  onView: (source: KnowledgeSource) => void;
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
          title="Couldn't load"
          description={error}
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
          <th className="px-5 py-3">Added</th>
          <th className="px-5 py-3" />
        </tr>
      </thead>
      <tbody className="divide-y divide-border">
        {sources.map((source) => (
          <tr key={source.id}>
            <td className="px-5 py-3 font-semibold">{source.title}</td>
            <td className="px-5 py-3 capitalize text-muted-foreground">{source.type}</td>
            <td className="px-5 py-3">
              <Badge tone={statusTone(source.status)}>{statusLabel(source.status)}</Badge>
            </td>
            <td className="px-5 py-3 text-muted-foreground">
              {source.createdAt ? new Date(source.createdAt).toLocaleDateString() : "—"}
            </td>
            <td className="px-5 py-3">
              <div className="flex items-center justify-end gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onView(source)}
                  aria-label={`${source.type === "manual" ? "Edit" : "View"} ${source.title}`}
                >
                  <Pencil className="h-4 w-4" />
                </Button>
                <Button variant="ghost" size="sm" onClick={() => onDelete(source)} aria-label={`Delete ${source.title}`}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
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
          title="Couldn't load"
          description={error}
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
