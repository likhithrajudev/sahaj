import { useUi } from "@/store/ui";

/** Applies the theme to <html data-theme>, following the system setting when the person chose "system". */
export function applyTheme() {
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const apply = () => {
    const { theme } = useUi.getState();
    const dark = theme === "dark" || (theme === "system" && media.matches);
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", dark ? "#0B1526" : "#F5F5F5");
  };
  apply();
  media.addEventListener("change", apply);
  useUi.subscribe((s, prev) => s.theme !== prev.theme && apply());
  useUi.subscribe((s, prev) => s.lang !== prev.lang && (document.documentElement.lang = s.lang === "hi" ? "hi" : "en-IN"));
  document.documentElement.lang = useUi.getState().lang === "hi" ? "hi" : "en-IN";
}
