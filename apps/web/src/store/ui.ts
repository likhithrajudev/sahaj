import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { UiLang } from "@/lib/i18n";

export type Theme = "system" | "light" | "dark";
export type Sheet = null | "menu" | "citations" | "install" | "mic" | "about" | "trust" | "documents" | "claim" | "loan";
/** The trust badges a reply can carry (see Verification in @sahaj/contracts). */
export type TrustLevel = "verified" | "engine" | "checked";

interface UiState {
  lang: UiLang;
  theme: Theme;
  /** The person has seen the mic explainer (shown once, before the browser's permission prompt). */
  micExplained: boolean;
  installDismissed: boolean;
  sheet: Sheet;
  /** Citations sheet: the assistant message and the citation to highlight. */
  citation: { itemId: string; citationId: string } | null;
  /** Trust sheet: the badge that was tapped, shown highlighted. */
  trustLevel: TrustLevel | null;
  /** Desktop side panel: which card is open (null = latest). */
  panelItemId: string | null;
  panelOpen: boolean;
  confirmWithdraw: null | import("@sahaj/contracts").ConsentPurpose;
  /** Android/desktop Chrome: the inline "Add Sahaj to your home screen" card in the conversation. */
  installCard: boolean;
}

const browserLang: UiLang = typeof navigator !== "undefined" && navigator.language?.toLowerCase().startsWith("hi") ? "hi" : "en";

export const useUi = create<UiState>()(
  persist(
    (): UiState => ({
      lang: browserLang,
      theme: "system",
      micExplained: false,
      installDismissed: false,
      sheet: null,
      citation: null,
      trustLevel: null,
      panelItemId: null,
      panelOpen: true,
      confirmWithdraw: null,
      installCard: false,
    }),
    {
      name: "sahaj-ui",
      // only preferences survive a reload; open sheets don't
      partialize: (s) => ({ lang: s.lang, theme: s.theme, micExplained: s.micExplained, installDismissed: s.installDismissed }),
    },
  ),
);

export const openSheet = (sheet: Sheet) => useUi.setState({ sheet });
export const closeSheet = () => useUi.setState({ sheet: null, citation: null });
