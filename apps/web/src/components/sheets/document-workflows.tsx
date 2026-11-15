import type { FilesResponse, StoredFile } from "@sahaj/contracts";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Sheet } from "@/components/ui/sheet";
import { api, apiResponse } from "@/lib/auth";
import { rupees } from "@/lib/utils";
import { selectDocument } from "@/lib/session";
import { useSession } from "@/store/session";
import { closeSheet, openSheet, useUi } from "@/store/ui";

type Kind = "claim" | "loan";
type Attachment = { id: string; filename: string; type: string; fields: Record<string, string>; method: string };
type Offer = { label: string; principal: number; net_disbursed: number; charges: number; months: number;
  monthly_rounded: number; total_repayment: number; apr_percent: number; source_url: string };
type Draft = {
  id: string; kind: Kind; documents: Attachment[]; revision: number; status: "draft" | "ready" | "submitted";
  fields: Record<string, string>; field_labels: Record<string, string>; reviewed: Record<string, string>;
  checklist: Record<string, boolean>; conflicts: Record<string, string[]>; missing_fields: string[];
  reference: string | null; submitted_at: string | null; checklist_source_url?: string; offer?: Offer;
};

function useDocumentPermissions(open: boolean) {
  const [data, setData] = useState<FilesResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setData(await api<FilesResponse>("/files"));
      setError("");
    } catch (cause) {
      setError(message(cause));
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    void refresh();
  }, [open, refresh]);

  const pending = data && (!data.consent ? data.consent_text : !data.analysis_consent ? data.analysis_consent_text : null);
  const allow = async () => {
    if (!pending) return;
    setLoading(true);
    try {
      await api(`/consents/${pending.purpose}`, {
        method: "PUT", body: JSON.stringify({ granted: true, version: pending.version }),
      });
      await refresh();
    } catch (cause) {
      setError(message(cause));
    } finally {
      setLoading(false);
    }
  };
  return { data, error, pending, refresh, allow, loading, granted: !!data?.consent && !!data.analysis_consent };
}

function message(cause: unknown) {
  return cause instanceof Error ? cause.message : "Something went wrong. Please try again.";
}

function Heading({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="mb-4">
    <div className="flex items-center justify-between gap-2">
      <h2 className="text-[22px] font-semibold">{title}</h2>
      <button type="button" onClick={closeSheet} className="flex size-11 shrink-0 items-center justify-center rounded-full"
        aria-label="Close"><Icon name="close" /></button>
    </div>
    {children}
  </div>;
}

function PermissionGate({ permissions, children }: { permissions: ReturnType<typeof useDocumentPermissions>; children: ReactNode }) {
  return <>
    {permissions.error && <p role="alert" className="mb-3 text-error-ink">{permissions.error} <button type="button"
      className="text-primary underline" onClick={() => void permissions.refresh()}>Retry</button></p>}
    {permissions.pending ? <div className="mb-5 rounded-card bg-surface-2 p-4">
      <p className="whitespace-pre-line">{permissions.pending.text}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="md" onClick={() => void permissions.allow()} disabled={permissions.loading}>Allow</Button>
        <Button size="md" variant="neutral" onClick={closeSheet}>Not now</Button>
      </div>
    </div> : permissions.granted ? children : !permissions.error && <p role="status">Checking permission…</p>}
  </>;
}

function FilePicker({ label, accept, busy, onPick }: { label: string; accept: string; busy: boolean; onPick: (file: File) => void }) {
  return <label className="block rounded-control border border-control-line bg-surface px-4 py-3 font-semibold">
    {label}
    <input type="file" accept={accept} disabled={busy}
      className="mt-2 block w-full max-w-full text-sm text-ink-2 file:mr-2 file:rounded-chip file:border-0 file:bg-primary-soft file:px-2 file:py-1 file:text-primary"
      onChange={(event) => {
        const file = event.currentTarget.files?.[0];
        event.currentTarget.value = "";
        if (file) onPick(file);
      }} />
  </label>;
}

export async function openDocument(path: string, page?: number) {
  const tab = window.open("", "_blank");
  if (tab) tab.opener = null;
  try {
    const response = await apiResponse(path);
    const url = URL.createObjectURL(await response.blob());
    const target = page ? `${url}#page=${page}` : url;
    if (tab) tab.location.replace(target);
    else {
      const link = document.createElement("a");
      link.href = target;
      link.target = "_blank";
      link.rel = "noopener";
      link.click();
    }
    setTimeout(() => URL.revokeObjectURL(url), 120_000);
  } catch (cause) {
    tab?.close();
    throw cause;
  }
}

export function PolicyDocumentsSheet() {
  const open = useUi((state) => state.sheet === "documents");
  const permissions = useDocumentPermissions(open);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const selection = useSession((state) => state.selectedDocument);
  const selecting = useSession((state) => state.selectingDocument);
  const scopeError = useSession((state) => state.documentScopeError);
  const docs = permissions.data?.items.filter((file) => file.content_type === "application/pdf") ?? [];
  const indexing = docs.some((file) => file.index_status === "indexing");
  const latest = permissions.refresh;

  useEffect(() => {
    if (!open || !indexing) return;
    const timer = setInterval(() => { void latest(); }, 2000);
    return () => clearInterval(timer);
  }, [open, indexing, latest]);

  async function upload(file: File) {
    setBusy(true);
    setError("");
    try {
      if (!file.name.toLowerCase().endsWith(".pdf")) throw new Error("Choose a policy PDF.");
      const form = new FormData();
      form.append("file", file);
      await api<StoredFile>("/files", { method: "POST", body: form });
      await permissions.refresh();
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(false);
    }
  }

  return <Sheet open={open} onClose={closeSheet} label="Policy documents">
    <div className="pb-5">
      <Heading title="Policy documents"><p className="text-ink-2">Upload a policy PDF, then choose it to ask Sahaj about its terms.</p></Heading>
      <PermissionGate permissions={permissions}>
        <FilePicker label="Add policy PDF" busy={busy} accept=".pdf,application/pdf" onPick={(file) => void upload(file)} />
        {busy && <p className="mt-2 text-info" role="status">Uploading…</p>}
        {error && <p className="mt-2 text-error-ink" role="alert">{error}</p>}
        {scopeError && <p className="mt-2 text-error-ink" role="alert">{scopeError}</p>}
        {!docs.length && <p className="mt-4 text-ink-2">No policy PDFs yet.</p>}
        <ul className="my-3 divide-y divide-line">
          {docs.map((file) => <li key={file.id} className="py-3">
            <p className="break-words font-semibold">{file.filename}</p>
            <p className="text-sm text-ink-2">
              {file.index_status === "ready" ? `Ready · ${file.indexed_chunks} passages${file.indexed_pages?.length ? ` · ${file.indexed_pages.length} of ${file.total_pages ?? "?"} pages` : ""}`
                : file.index_status === "indexing" ? "Indexing…" : file.index_status === "none" ? "Indexing hasn’t started" : `Unavailable · ${file.index_status.replace("_", " ")}`}
            </p>
            {typeof file.total_pages === "number" && file.indexed_pages && file.indexed_pages.length < file.total_pages &&
              <p className="mt-1 text-sm text-warn">Partial index. Answers use the pages Sahaj could read.</p>}
            {file.index_status === "ready" && (file.id === selection?.id
              ? <div className="mt-2 flex flex-wrap gap-2">
                <Button size="md" onClick={closeSheet}>Back to conversation</Button>
                <Button size="md" variant="neutral" disabled={selecting} onClick={() => selectDocument(null)}>Clear selection</Button>
              </div>
              : <Button size="md" variant="soft" className="mt-2" disabled={selecting}
                  onClick={() => selectDocument(file.id)}>{file.total_pages && file.indexed_pages && file.indexed_pages.length < file.total_pages ? "Ask about indexed pages" : "Ask about this policy"}</Button>)}
          </li>)}
        </ul>
        <Button size="md" variant="neutral" onClick={() => void permissions.refresh()}>Refresh list</Button>
      </PermissionGate>
    </div>
  </Sheet>;
}

const fieldClass = "mt-1 w-full rounded-control border border-control-line bg-surface px-3 py-2 text-ink";
const amountFields = new Set(["hospital_total", "pharmacy_total", "net_pay"]);

function LoanOffer({ offer }: { offer: Offer }) {
  return <section className="mb-4 rounded-card border border-line bg-loan-soft p-4">
    <h3 className="font-semibold">{offer.label}</h3>
    <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
      {[
        ["Amount borrowed", rupees(offer.principal)], ["Upfront charges", rupees(offer.charges)],
        ["Money received", rupees(offer.net_disbursed)], ["Monthly (rounded)", `${rupees(offer.monthly_rounded)} × ${offer.months}`],
        ["Total repayment", rupees(offer.total_repayment)], ["APR", `${offer.apr_percent}%`],
      ].map(([label, value]) => <div key={label}><dt className="text-ink-2">{label}</dt><dd className="font-semibold">{value}</dd></div>)}
    </dl>
    <a href={offer.source_url} target="_blank" rel="noreferrer" className="mt-3 inline-flex min-h-11 items-center text-primary underline">RBI worked example</a>
  </section>;
}

function DraftContents({ kind }: { kind: Kind }) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const edits = Object.fromEntries(Object.entries(fields).filter(([key, value]) => value !== (draft?.fields[key] ?? "")));

  function update(next: Draft, keepEdits = false) {
    setDraft(next);
    const applicable = keepEdits ? Object.entries(edits).filter(([key]) => key in next.field_labels) : [];
    setFields({ ...next.fields, ...Object.fromEntries(applicable) });
  }

  async function action(work: () => Promise<void>, pending = "") {
    setBusy(true);
    setError("");
    setNotice(pending);
    try {
      await work();
      setNotice("");
    } catch (cause) {
      setError(message(cause));
      setNotice("");
    } finally {
      setBusy(false);
    }
  }

  async function create() {
    update(await api<Draft>("/drafts", { method: "POST", body: JSON.stringify({ kind }) }));
  }

  useEffect(() => {
    void action(async () => {
      const drafts = await api<Draft[]>("/drafts");
      const latest = drafts.find((item) => item.kind === kind);
      if (latest) update(latest);
    }, "Loading draft…");
  }, [kind]);

  function upload(file: File) {
    if (!draft) return;
    void action(async () => {
      const form = new FormData();
      form.append("file", file);
      update(await api<Draft>(`/drafts/${draft.id}/attachments`, { method: "POST", body: form }), true);
    }, "Reading document…");
  }

  function review(confirm: boolean) {
    if (!draft) return;
    void action(async () => {
      update(await api<Draft>(`/drafts/${draft.id}/review`, { method: "PATCH",
        body: JSON.stringify({ fields: edits, confirm, revision: draft.revision }) }));
    }, "Saving draft…");
  }

  const complete = draft?.status === "submitted";
  const fieldsChanged = Object.keys(edits).length > 0;
  return <>
    {notice && <p role="status" className="mb-3 text-info">{notice}</p>}
    {error && <p role="alert" className="mb-3 text-error-ink">{error}</p>}
    {!draft && !busy && <Button size="md" onClick={() => void action(create)}>Start draft</Button>}
    {draft && <>
      {draft.offer && <LoanOffer offer={draft.offer} />}
      {complete && <section className="mb-4 rounded-card bg-success-soft p-4 text-success">
        <h3 className="font-semibold">Demo submission saved</h3>
        <p className="mt-1">Reference {draft.reference}</p>
        <p className="mt-1 text-sm">Simulated submission</p>
      </section>}
      {!complete && <FilePicker label="Add document" accept="application/pdf,image/jpeg,image/png"
        busy={busy} onPick={upload} />}
      <ul className="my-3 divide-y divide-line">
        {draft.documents.map((doc) => <li key={doc.id} className="flex items-center justify-between gap-2 py-2">
          <div className="min-w-0">
            <p className="font-semibold">{doc.type}</p>
            <p className="break-words text-sm text-ink-2">{doc.filename} · {doc.method === "ocr" ? "OCR" : "PDF text"}</p>
          </div>
          <div className="flex flex-wrap justify-end gap-1">
            <Button size="inline" variant="link" onClick={() => void action(() =>
                openDocument(`/drafts/${draft.id}/attachments/${doc.id}`))}>View</Button>
            {!complete && <Button size="inline" variant="link" disabled={busy} onClick={() => void action(async () => {
              update(await api<Draft>(`/drafts/${draft.id}/attachments/${doc.id}`, { method: "DELETE" }), true);
            })}>Remove</Button>}
          </div>
        </li>)}
      </ul>
      <section className="mb-4 rounded-card bg-surface-2 p-4">
        <h3 className="font-semibold">Demo checklist</h3>
        <ul className="mt-1 divide-y divide-line">
          {Object.entries(draft.checklist).map(([label, done]) => <li key={label} className="flex justify-between gap-2 py-1.5">
            <span>{label}</span><span className={done ? "font-semibold text-success" : "font-semibold text-warn"}>{done ? "Added" : "Missing"}</span>
          </li>)}
        </ul>
        {draft.checklist.Prescription === false && <p className="mt-2 text-sm text-warn">Add the prescription that goes with the pharmacy bill.</p>}
        {draft.checklist_source_url && <a href={draft.checklist_source_url} target="_blank" rel="noreferrer"
          className="inline-flex min-h-11 items-center text-primary underline">Star Health reimbursement checklist</a>}
      </section>
      <div className="space-y-3">
        <h3 className="font-semibold">Review draft</h3>
        {Object.entries(draft.field_labels).map(([key, label]) => {
          const source = draft.documents.find((doc) => doc.fields[key]);
          const id = `draft-${draft.id}-${key}`;
          const conflict = draft.conflicts[key];
          const note = conflict ? "Conflicting values. Review the documents and enter the correct one."
            : key in draft.reviewed ? "Edited in this draft"
              : source ? `Read from ${source.type.toLowerCase()}` : "";
          return <div key={key}>
            <label className="block" htmlFor={id}>{label}</label>
            <input id={id} aria-describedby={note ? `${id}-hint` : undefined}
              className={fieldClass} value={fields[key] ?? ""} disabled={busy || complete}
              inputMode={amountFields.has(key) ? "decimal" : "text"} type={["admitted", "discharged"].includes(key) ? "date" : "text"}
              maxLength={160} onChange={(event) => setFields({ ...fields, [key]: event.target.value })} />
            {note && <small id={`${id}-hint`} className={conflict ? "text-warn" : "text-ink-2"}>{note}</small>}
          </div>;
        })}
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        {complete ? <Button size="md" variant="neutral" disabled={busy} onClick={() => void action(create)}>Start another draft</Button>
          : <>
            <Button size="md" variant="neutral" disabled={busy} onClick={() => review(false)}>Save draft</Button>
            {draft.status === "ready" && !fieldsChanged
              ? <Button size="md" disabled={busy} onClick={() => void action(async () => {
                update(await api<Draft>(`/drafts/${draft.id}/submit`, { method: "POST", body: JSON.stringify({ revision: draft.revision }) }));
              })}>{kind === "claim" ? "Submit demo claim" : "Submit demo application"}</Button>
              : <Button size="md" disabled={busy} onClick={() => review(true)}>Confirm details</Button>}
          </>}
      </div>
    </>}
  </>;
}

export function JourneySheet() {
  const active = useUi((state) => state.sheet);
  const open = active === "claim" || active === "loan";
  const kind = active === "loan" ? "loan" : "claim";
  const title = kind === "claim" ? "Prepare a claim" : "Prepare a loan application";
  const permissions = useDocumentPermissions(open);

  return <Sheet open={open} onClose={closeSheet} label={title}>
    <div className="pb-5">
      <Heading title={title}><p className="text-ink-2">Sahaj reads the files you choose and saves the draft to this account. Use fictional files for this demo.</p></Heading>
      <PermissionGate permissions={permissions}>{open && <DraftContents key={kind} kind={kind} />}</PermissionGate>
    </div>
  </Sheet>;
}

export function DocumentScopeBar() {
  const document = useSession((state) => state.selectedDocument);
  const selecting = useSession((state) => state.selectingDocument);
  if (!document) return null;
  return <div className="mx-4 mb-2 flex items-center gap-3 rounded-control border border-line bg-primary-soft px-3 text-primary">
    <Icon name="description" size={19} />
    <span className="min-w-0 flex-1 truncate text-sm">
      {document.unavailable ? "Selected PDF unavailable" : `Asking about ${document.name}`}
    </span>
    <Button size="inline" variant="link" disabled={selecting} onClick={() => openSheet("documents")}>Change</Button>
    <button type="button" aria-label="Clear policy selection" disabled={selecting}
      className="flex size-11 shrink-0 items-center justify-center" onClick={() => selectDocument(null)}>
      <Icon name="close" size={18} />
    </button>
  </div>;
}
