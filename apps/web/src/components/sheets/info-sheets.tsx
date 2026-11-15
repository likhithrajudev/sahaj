import { useEffect, useState } from "react";
import { LogoMark } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Sheet } from "@/components/ui/sheet";
import { TRUST_ICON } from "@/components/conversation/messages";
import { useT, type StringKey } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { pwa } from "@/pwa";
import { closeSheet, useUi } from "@/store/ui";

export function InstallSheet() {
  const t = useT();
  const open = useUi((s) => s.sheet === "install");
  const [canPrompt, setCanPrompt] = useState(pwa.canPrompt());
  useEffect(() => {
    const off = pwa.onChange(() => setCanPrompt(pwa.canPrompt()));
    return () => void off();
  }, []);
  const later = () => { useUi.setState({ installDismissed: true }); closeSheet(); };

  return (
    <Sheet open={open} onClose={later} label={t("installTitle")}>
      <div className="flex flex-col gap-4 pb-2">
        <h2 className="text-[22px] font-semibold leading-7">{t("installTitle")}</h2>
        {canPrompt ? (
          <>
            <div className="flex items-center gap-3 rounded-2xl bg-bg p-4">
              <LogoMark size={52} />
              <div className="flex flex-col"><span className="text-lg font-semibold">Sahaj</span><span className="text-sm text-ink-2">{t("tagline")}</span></div>
            </div>
            <p className="text-[17px] leading-[25px] text-ink-2">{t("installBody")}</p>
            <Button onClick={async () => { await pwa.prompt(); closeSheet(); }}>{t("install")}</Button>
          </>
        ) : (
          <ol className="flex flex-col gap-4">
            {([["iosStep1", "ios_share"], ["iosStep2", "add_box"], ["iosStep3", null]] as const).map(([key, icon], i) => (
              <li key={key} className="flex items-center gap-3.5">
                <span className="flex size-8 flex-none items-center justify-center rounded-full bg-surface-2 text-[15px] font-bold text-primary">{i + 1}</span>
                <span className="flex-1 text-[17px] leading-6">{t(key)}</span>
                {icon && <span className="flex size-11 items-center justify-center rounded-xl bg-surface-2 text-primary"><Icon name={icon} /></span>}
              </li>
            ))}
          </ol>
        )}
        <Button variant="neutral" onClick={later}>{t("later")}</Button>
        {!canPrompt && pwa.isIOS() && (
          <p className="flex items-center justify-center gap-1.5 text-sm text-ink-2">{t("shareHere")} <Icon name="south" size={18} /></p>
        )}
      </div>
    </Sheet>
  );
}

export function AboutSheet() {
  const t = useT();
  const open = useUi((s) => s.sheet === "about");
  return (
    <Sheet open={open} onClose={closeSheet} label={t("menuAbout")}>
      <div className="flex flex-col gap-4 pb-4">
        <div className="flex items-center gap-3">
          <LogoMark size={44} />
          <h2 className="text-[22px] font-semibold">Sahaj</h2>
        </div>
        <p className="text-[17px] leading-[25px] text-ink-2">{t("aboutBody")}</p>
        <Button variant="neutral" onClick={closeSheet}>{t("gotIt")}</Button>
      </div>
    </Sheet>
  );
}

const TRUST: { level: "verified" | "engine" | "checked"; name: StringKey; body: StringKey }[] = [
  { level: "verified", name: "trustVerifiedName", body: "trustVerifiedBody" },
  { level: "engine", name: "engine", body: "trustEngineBody" },
  { level: "checked", name: "checked", body: "trustCheckedBody" },
];

/** What the trust label on a reply means (opened by tapping the label). The tapped one is highlighted. */
export function TrustSheet() {
  const t = useT();
  const open = useUi((s) => s.sheet === "trust");
  const current = useUi((s) => s.trustLevel);
  return (
    <Sheet open={open} onClose={closeSheet} label={t("trustTitle")}>
      <div className="flex flex-col gap-4 pb-4">
        <h2 className="text-[22px] font-semibold leading-7">{t("trustTitle")}</h2>
        <ul className="flex flex-col gap-2.5">
          {TRUST.map(({ level, name, body }) => (
            <li key={level} aria-current={level === current || undefined}
              className={cn("flex gap-3 rounded-2xl border p-3.5", level === current ? "border-success bg-bg" : "border-line")}>
              <span className="flex size-10 flex-none items-center justify-center rounded-xl bg-surface-2 text-success">
                <Icon name={TRUST_ICON[level]} />
              </span>
              <div className="flex min-w-0 flex-col gap-0.5">
                <span className="flex flex-wrap items-center gap-2 text-[17px] font-semibold">
                  {t(name)}
                  {level === current && <span className="rounded-full bg-surface-2 px-2 py-0.5 text-xs font-semibold text-ink-2">{t("trustThis")}</span>}
                </span>
                <span className="text-[15px] leading-[22px] text-ink-2">{t(body)}</span>
              </div>
            </li>
          ))}
        </ul>
        <p className="text-sm leading-5 text-ink-2">{t("trustBlocked")}</p>
        <Button variant="neutral" onClick={closeSheet}>{t("gotIt")}</Button>
      </div>
    </Sheet>
  );
}

/** Android: offered inside the conversation after the first answer. */
export function InstallCard() {
  const t = useT();
  const show = useUi((s) => s.installCard && !s.installDismissed);
  if (!show || pwa.isStandalone()) return null;
  const later = () => useUi.setState({ installCard: false, installDismissed: true });
  return (
    <section className="flex flex-col gap-3 rounded-[20px] border border-line bg-surface p-4">
      <div className="flex gap-3">
        <LogoMark size={40} />
        <div className="flex flex-col">
          <span className="text-[17px] font-semibold">{t("installTitle")}</span>
          <span className="text-sm leading-5 text-ink-2">{t("installBody")}</span>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Button variant="neutral" size="md" onClick={later}>{t("later")}</Button>
        <Button size="md" onClick={async () => { await pwa.prompt(); later(); }}>{t("install")}</Button>
      </div>
    </section>
  );
}
