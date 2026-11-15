import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Sheet } from "@/components/ui/sheet";
import { useT, type StringKey } from "@/lib/i18n";
import { consentNotice, requestVideoKyc } from "@/lib/session";
import { kycCase, useSession, withPerson } from "@/store/session";
import { closeAllSheets, closeSheet, useSheet } from "@/store/ui";

const STEPS: [StringKey, StringKey][] = [["kycStep1", "kycStep1Body"], ["kycStep2", "kycStep2Body"], ["kycStep3", "kycStep3Body"]];

/** What video KYC is, and the request for an appointment (with its permission, agreed here in one step). */
export function KycSheet() {
  const t = useT();
  const { open } = useSheet("kyc");
  const active = useSession(kycCase);
  const otherCase = useSession((s) => withPerson(s) && !kycCase(s));
  const granted = useSession((s) => s.consent.video_kyc.state === "granted");
  const connected = useSession((s) => s.connection === "open");
  const [note, setNote] = useState("");
  const notice = open && !granted ? consentNotice("video_kyc") : null;

  const request = () => {
    if (requestVideoKyc({ agreed: true, note })) {
      setNote("");
      closeAllSheets();
    }
  };

  return (
    <Sheet name="kyc" onClose={closeSheet} label={t("kycTitle")}>
      <div className="flex flex-col gap-5 pb-4">
        <div className="flex items-center gap-3.5">
          <span className="flex size-12 flex-none items-center justify-center rounded-2xl text-white shadow-talk" style={{ background: "var(--hero)" }}>
            <Icon name="videocam" size={26} />
          </span>
          <h2 className="text-[24px] font-semibold leading-[30px] tracking-[-0.015em]">{t("kycTitle")}</h2>
        </div>
        <p className="text-[17px] leading-[25px] text-ink-2">{t("kycIntro")}</p>

        <ol className="flex flex-col gap-3.5">
          {STEPS.map(([title, body], i) => (
            <li key={title} className="flex items-start gap-3.5">
              <span className="flex size-8 flex-none items-center justify-center rounded-full bg-primary-soft text-[15px] font-bold text-primary">{i + 1}</span>
              <span className="flex flex-col">
                <span className="text-[17px] font-semibold leading-6">{t(title)}</span>
                <span className="text-[15px] leading-[21px] text-ink-2">{t(body)}</span>
              </span>
            </li>
          ))}
        </ol>

        {active ? (
          <Button onClick={closeAllSheets}><Icon name="event_available" size={20} /> {t("kycShow")}</Button>
        ) : (
          <>
            {otherCase && (
              <p className="flex gap-2 rounded-xl bg-info-soft px-3 py-2.5 text-sm leading-5 text-ink">
                <Icon name="info" size={18} className="flex-none text-info" /> {t("kycOpenCase")}
              </p>
            )}
            <label className="flex flex-col gap-1.5">
              <span className="text-[15px] font-semibold text-ink-2">{t("kycNoteLabel")}</span>
              <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} placeholder={t("kycNotePlaceholder")}
                className="h-12 rounded-xl border border-line-2 bg-surface px-3.5 text-[17px] outline-none transition-[border-color,box-shadow] placeholder:text-ink-3 focus:border-primary focus:ring-4 focus:ring-primary/15" />
            </label>
            {notice && (
              <div className="rounded-2xl bg-surface-muted p-4">
                <h3 className="flex items-center gap-2 text-[15px] font-semibold"><Icon name="shield_person" size={20} className="text-primary" /> {t("kycPermission")}</h3>
                <p className="mt-2 max-h-40 overflow-y-auto whitespace-pre-line text-[15px] leading-[22px] text-ink-2">{notice.text}</p>
                <p className="mt-2 text-[13px] text-ink-3">{t("consentNotice")} {notice.version} · {t("purposeKyc")}</p>
              </div>
            )}
            <p className="flex gap-2 text-sm leading-5 text-ink-3"><Icon name="shield_person" size={18} className="flex-none" /> {t("kycWho")}</p>
            <div className="flex flex-col gap-2.5">
              <Button onClick={request} disabled={!connected}>
                <Icon name="event_available" size={20} /> {t(granted || !notice ? "kycRequest" : "kycAgreeRequest")}
              </Button>
              <Button variant="neutral" onClick={closeSheet}>{t("notNow")}</Button>
            </div>
          </>
        )}
      </div>
    </Sheet>
  );
}
