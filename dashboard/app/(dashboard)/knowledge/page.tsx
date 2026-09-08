"use client";

import {
  BookOpen,
  FileUp,
  Globe,
  HelpCircle,
  Pencil,
  Plus,
  RefreshCw,
  RotateCw,
  Trash2,
  Wand2,
} from "lucide-react";
import { useEffect, useRef, useState, type DragEvent, type FormEvent } from "react";

import { AnswerGapDialog } from "@/components/knowledge/answer-gap-dialog";
import { KnowledgeCaps } from "@/components/knowledge/knowledge-caps";
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
  type KnowledgeGapKind,
} from "@/lib/api";
import { knowledgeExtras, type KnowledgeSourceDetail } from "@/lib/api/knowledge-extras";
import { formatDate, formatRelative } from "@/lib/format";
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
  const [urlOpen, setUrlOpen] = useState(false);
  const [editing, setEditing] = useState<KnowledgeSource | null>(null);
  const [answering, setAnswering] = useState<KnowledgeGap | null>(null);

  const { data, loading, error, refetch } = useApi(
    () => knowledgeExtras.listSources({ token }),
    [token],
  );
  const {
    data: usage,
    loading: usageLoading,
    refetch: refetchUsage,
  } = useApi(() => knowledgeExtras.usage({ token }), [token]);
  const {
    data: gaps,
    loading: gapsLoading,
    error: gapsError,
    refetch: refetchGaps,
  } = useApi(() => knowledge.gaps({ token }), [token]);

  // Anything that changes the sources changes the caps above them, so the two
  // reads are refreshed together. A meter left at its previous value after an
  // upload is worse than no meter: it is a number the owner will trust.
  function refetchSources() {
    refetch();
    refetchUsage();
  }

  async function handleDelete(source: KnowledgeSource) {
    if (!window.confirm(`Delete "${source.title}"? This can't be undone.`)) return;
    try {
      await knowledge.deleteSource(source.id, { token });
      toast({ title: "Source deleted", variant: "success" });
      refetchSources();
    } catch (err) {
      toast({ title: "Couldn't delete source", description: describeError(err), variant: "error" });
    }
  }

  async function handleRefetch(source: KnowledgeSourceDetail) {
    try {
      await knowledgeExtras.refetchSource(source.id, { token });
      toast({
        title: source.url ? "Re-crawling the page" : "Re-reading the file",
        description: "The status will turn Ready when it finishes.",
        variant: "success",
      });
      refetchSources();
    } catch (err) {
      toast({ title: "Couldn't refresh", description: describeError(err), variant: "error" });
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight">Knowledge</h1>
          <p className="text-sm text-muted-foreground">
            What your AI representative knows. Upload docs, write entries by hand, or review the gaps.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setUrlOpen(true)}>
            <Globe className="h-4 w-4" />
            Add website
          </Button>
          <Button onClick={() => setManualOpen(true)}>
            <Plus className="h-4 w-4" />
            Add entry
          </Button>
        </div>
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
          <UploadDropzone onUploaded={refetchSources} />

          <KnowledgeCaps usage={usage} loading={usageLoading} />

          <div className="overflow-hidden rounded-2xl border border-border bg-surface">
            <div className="flex items-center justify-between border-b border-border px-5 py-4">
              <h2 className="text-sm font-bold">Sources</h2>
              {/* "Refresh" at the top of a table of crawled websites read as
                  though it re-fetched them (teardown K2). Re-fetching is now a
                  per-row control; this one only reloads the list. */}
              <Button variant="ghost" size="sm" onClick={refetchSources}>
                <RefreshCw className="h-4 w-4" />
                Reload list
              </Button>
            </div>

            <SourcesTable
              sources={data}
              loading={loading}
              error={error}
              onRetry={refetchSources}
              onDelete={handleDelete}
              onView={setEditing}
              onRefetch={handleRefetch}
            />
          </div>
        </>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-border bg-surface">
          <div className="flex items-center justify-between border-b border-border px-5 py-4">
            <div>
              <h2 className="text-sm font-bold">Questions the bot couldn&apos;t answer</h2>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Answer one and it becomes knowledge, and drops off this list.
              </p>
            </div>
            <Button variant="ghost" size="sm" onClick={refetchGaps}>
              <RefreshCw className="h-4 w-4" />
              Reload list
            </Button>
          </div>
          <GapsTable
            gaps={gaps}
            loading={gapsLoading}
            error={gapsError}
            onRetry={refetchGaps}
            onAnswer={setAnswering}
          />
        </div>
      )}

      <AddManualEntryDialog
        open={manualOpen}
        onClose={() => setManualOpen(false)}
        onCreated={() => {
          setManualOpen(false);
          refetchSources();
        }}
      />

      <AddUrlDialog
        open={urlOpen}
        onClose={() => setUrlOpen(false)}
        onCreated={() => {
          setUrlOpen(false);
          refetchSources();
        }}
      />

      <ViewEditSourceDialog
        source={editing}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          refetchSources();
        }}
      />

      <AnswerGapDialog
        gap={answering}
        onClose={() => setAnswering(null)}
        onAnswered={() => {
          setAnswering(null);
          // Both lists move: the gap is answered and a source now exists. The
          // owner switching to Sources to check has to find it there.
          refetchGaps();
          refetchSources();
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
      description={editable ? "Update the title or content. Saving re-indexes it." : "Extracted content (read-only)."}
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

function AddUrlDialog({
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
  const [url, setUrl] = useState("");
  const [saving, setSaving] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!title.trim() || !url.trim()) return;
    setSaving(true);
    try {
      await knowledge.addUrlSource({ title: title.trim(), url: url.trim() }, { token });
      toast({ title: "Website added", description: "We're fetching and indexing the page.", variant: "success" });
      setTitle("");
      setUrl("");
      onCreated();
    } catch (err) {
      toast({ title: "Couldn't add website", description: describeError(err), variant: "error" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Add a website"
      description="We'll fetch the page, extract its text, and add it to your rep's knowledge."
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="url-title">Title</Label>
          <Input
            id="url-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Our FAQ page"
            required
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="url-address">URL</Label>
          <Input
            id="url-address"
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://yourbusiness.com/faq"
            required
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={saving}>
            {saving ? "Adding…" : "Add website"}
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
        <p className="text-xs text-danger">Upload failed. Please try again.</p>
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
  onRefetch,
}: {
  sources: KnowledgeSourceDetail[] | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onDelete: (source: KnowledgeSource) => void;
  onView: (source: KnowledgeSource) => void;
  onRefetch: (source: KnowledgeSourceDetail) => void;
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
        {/* The most valuable empty state in the product: this is the screen
            where a rep stops saying "I do not know" and starts being useful.
            So it names what to upload rather than describing the feature.
            "Add a manual entry above to start grounding replies" told an owner
            what the page does, which they could already see. */}
        <EmptyState
          icon={<BookOpen className="h-5 w-5" />}
          title="Your rep does not know anything yet"
          description="Until you add something here it will tell customers it cannot help. Start with whatever you get asked most: a price list, your opening hours, a returns or booking policy, or your website."
        />
      </div>
    );
  }

  return (
    // The table scrolls inside itself. Six columns do not fit a phone, and a
    // page body that scrolls sideways is the other way to get this wrong.
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-sm">
        <thead className="text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
          <tr>
            <th className="px-5 py-3">Title</th>
            <th className="px-5 py-3">Type</th>
            <th className="px-5 py-3">Size</th>
            <th className="px-5 py-3">Last indexed</th>
            <th className="px-5 py-3">Status</th>
            <th className="px-5 py-3">Added</th>
            <th className="px-5 py-3" />
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {sources.map((source) => (
            <tr key={source.id}>
              <td className="max-w-[22rem] px-5 py-3">
                <p className="truncate font-semibold">{source.title}</p>
                {source.url ? (
                  <p className="truncate text-xs text-muted-foreground" title={source.url}>
                    {source.url}
                  </p>
                ) : null}
              </td>
              <td className="px-5 py-3 capitalize text-muted-foreground">{source.type}</td>
              <td className="px-5 py-3 text-muted-foreground">
                <SourceSize source={source} />
              </td>
              <td className="px-5 py-3 text-muted-foreground">
                {/* A website fetched six weeks ago used to look exactly like one
                    fetched this morning (teardown K2). Relative, because "how
                    stale is this" is the only question being asked of it. */}
                {source.lastIngestedAt ? formatRelative(source.lastIngestedAt) : "Never"}
              </td>
              <td className="px-5 py-3">
                <Badge tone={statusTone(source.status)}>{statusLabel(source.status)}</Badge>
              </td>
              <td className="whitespace-nowrap px-5 py-3 text-muted-foreground">
                {formatDate(source.createdAt)}
              </td>
              <td className="px-5 py-3">
                <div className="flex items-center justify-end gap-1">
                  {/* Only for sources whose text lives elsewhere. A manual
                      entry has nothing to re-fetch, and the backend refuses it. */}
                  {source.url || source.uploadBytes !== null ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => onRefetch(source)}
                      aria-label={`${source.url ? "Re-crawl" : "Re-read"} ${source.title}`}
                      title={source.url ? "Crawl this page again" : "Read this file again"}
                    >
                      <RotateCw className="h-4 w-4" />
                    </Button>
                  ) : null}
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
    </div>
  );
}

/**
 * How much of a source the rep actually holds.
 *
 * Characters, because that is the cap it counts against and the only measure
 * that exists for every type. Deliberately not a "contribution" or "hit count":
 * retrieval hits are not recorded anywhere, and a number invented for a column
 * is worse than an empty column.
 */
function SourceSize({ source }: { source: KnowledgeSourceDetail }) {
  if (source.chars === 0) {
    return (
      <span title="Nothing indexed yet, so this source cannot be used in a reply">
        {source.status === "error" ? "Nothing indexed" : "Pending"}
      </span>
    );
  }
  return (
    <>
      <p className="tabular-nums">{source.chars.toLocaleString()} chars</p>
      <p className="text-xs">
        {source.chunks.toLocaleString()} {source.chunks === 1 ? "passage" : "passages"}
        {source.uploadBytes !== null ? ` · ${formatBytes(source.uploadBytes)}` : ""}
      </p>
    </>
  );
}

/** Upload size for a person: "1.4 MB", not 1468006. */
function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function GapsTable({
  gaps,
  loading,
  error,
  onRetry,
  onAnswer,
}: {
  gaps: KnowledgeGap[] | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onAnswer: (gap: KnowledgeGap) => void;
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
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-sm">
        <thead className="text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
          <tr>
            <th className="px-5 py-3">Question</th>
            <th className="px-5 py-3">What happened</th>
            <th className="px-5 py-3">Times asked</th>
            <th className="px-5 py-3">Last asked</th>
            <th className="px-5 py-3" />
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {gaps.map((gap) => (
            <tr key={gap.id}>
              <td className="px-5 py-3 font-semibold">{gap.question}</td>
              <td className="px-5 py-3">
                <GapKind kind={gap.kind} reason={gap.reason} />
              </td>
              <td className="px-5 py-3 tabular-nums text-muted-foreground">{gap.count}</td>
              <td className="whitespace-nowrap px-5 py-3 text-muted-foreground">
                {formatRelative(gap.lastAsked)}
              </td>
              <td className="px-5 py-3">
                {/* The half that was missing (teardown K1). Knowing what the rep
                    could not answer is worth nothing from a page that offers no
                    way to answer it. */}
                <div className="flex justify-end">
                  <Button variant="outline" size="sm" onClick={() => onAnswer(gap)}>
                    <Wand2 className="h-4 w-4" />
                    Answer this
                  </Button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The kind is the actionable half. "Nothing found" means write something;
 * "answer not in your knowledge" means what you wrote does not answer this,
 * and adding more of the same will not help.
 */
function GapKind({ kind, reason }: { kind: KnowledgeGapKind; reason: string | null }) {
  const label: Record<KnowledgeGapKind, { text: string; tone: "warning" | "info" | "default" }> = {
    retrieval_miss: { text: "Nothing found", tone: "warning" },
    answer_miss: { text: "Answer not in your knowledge", tone: "info" },
    escalation: { text: "Passed to a person", tone: "default" },
  };
  const { text, tone } = label[kind] ?? label.escalation;

  return (
    <div className="space-y-1">
      <Badge tone={tone}>{text}</Badge>
      {reason ? <p className="text-xs text-muted-foreground">{reason}</p> : null}
    </div>
  );
}
