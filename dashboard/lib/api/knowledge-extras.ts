/**
 * Knowledge endpoints the shared client did not cover (teardown K1, K2, K3).
 *
 * A separate module rather than more of `lib/api.ts`, which is past a thousand
 * lines and is the file every concurrent change collides in -- see the note on
 * `apiFetch` there.
 *
 * What is here is the part of the knowledge API the page needed and could not
 * reach: the per-source measurements, the plan meters, the re-fetch, and the
 * gap answer. Creating, editing, deleting and listing gaps stay on
 * `knowledge.*` in `lib/api.ts` rather than being duplicated here.
 */

import { apiFetch, type CallOpts, type KnowledgeSource, type UsageMeter } from "@/lib/api";

interface KnowledgeSourceDetailDto {
  id: string;
  type: KnowledgeSource["type"];
  title: string;
  url: string | null;
  content: string | null;
  status: KnowledgeSource["status"];
  auto_refresh: boolean;
  created_at: string;
  chars: number;
  chunks: number;
  upload_bytes: number | null;
  last_ingested_at: string | null;
}

/**
 * A source, with the facts the table could not previously state.
 *
 * `chars` is what retrieval can actually return for this source, which is not
 * the same measure as the plan's character meter: that one counts every chunk
 * stored, including the tombstoned remains of an earlier crawl.
 */
export interface KnowledgeSourceDetail extends KnowledgeSource {
  chars: number;
  chunks: number;
  /** Bytes of the original upload; null for anything not uploaded. */
  uploadBytes: number | null;
  /** Last *successful* ingest. Null means it has never finished one. */
  lastIngestedAt: string | null;
}

function mapDetail(dto: KnowledgeSourceDetailDto): KnowledgeSourceDetail {
  return {
    id: dto.id,
    type: dto.type,
    title: dto.title,
    url: dto.url,
    content: dto.content,
    status: dto.status,
    createdAt: dto.created_at ?? null,
    chars: dto.chars ?? 0,
    chunks: dto.chunks ?? 0,
    uploadBytes: dto.upload_bytes ?? null,
    lastIngestedAt: dto.last_ingested_at ?? null,
  };
}

interface KnowledgeUsageDto {
  sources: number;
  max_sources: number;
  chars: number;
  max_chars: number;
  upload_bytes: number;
  max_upload_bytes: number;
  meters: { sources: UsageMeter; chars: UsageMeter; upload_mb: UsageMeter };
}

export interface KnowledgeUsage {
  /** Meter-shaped, `state` included. The backend owns the amber threshold. */
  sources: UsageMeter;
  chars: UsageMeter;
  uploadMb: UsageMeter;
}

export const knowledgeExtras = {
  /** The same GET as `knowledge.listSources`, keeping the per-source figures. */
  listSources: (opts: CallOpts = {}) =>
    apiFetch<KnowledgeSourceDetailDto[]>("/api/knowledge/sources", opts).then((items) =>
      items.map(mapDetail),
    ),

  usage: (opts: CallOpts = {}) =>
    apiFetch<KnowledgeUsageDto>("/api/knowledge/usage", opts).then(
      (dto): KnowledgeUsage => ({
        sources: dto.meters.sources,
        chars: dto.meters.chars,
        uploadMb: dto.meters.upload_mb,
      }),
    ),

  /** Re-crawl a website source, or re-read an upload already on the volume. */
  refetchSource: (id: string, opts: CallOpts = {}) =>
    apiFetch<KnowledgeSourceDetailDto>(`/api/knowledge/sources/${id}`, {
      method: "PUT",
      body: { refetch: true },
      ...opts,
    }).then(mapDetail),

  /**
   * Answer a gap: one call that stores the entry and marks the gap answered.
   *
   * Deliberately not two calls. A "mark resolved" that could succeed while the
   * entry failed would hide the question from the only person able to answer it.
   */
  answerGap: (
    payload: { gapId: string; title: string; content: string },
    opts: CallOpts = {},
  ) =>
    apiFetch<KnowledgeSourceDetailDto>("/api/knowledge/sources", {
      method: "POST",
      body: {
        type: "manual",
        title: payload.title,
        content: payload.content,
        answers_gap_id: payload.gapId,
      },
      ...opts,
    }).then(mapDetail),
};
