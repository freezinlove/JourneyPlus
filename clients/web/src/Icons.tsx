import s from "./App.module.css";
export function BrandMark() {
  return <span className={s.brandSymbol} aria-hidden="true" />;
}
export function NavIcon({
  name,
}: {
  name: "chat" | "news" | "account" | "back" | "new";
}) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      {name === "chat" ? (
        <>
          <path d="M20 11.5a8 8 0 0 1-8 8H5l-3 2v-10a9 9 0 0 1 18 0Z" />
          <path d="M7 10h8M7 14h5" />
        </>
      ) : name === "news" ? (
        <>
          <rect x="4" y="3" width="16" height="18" rx="3" />
          <path d="M8 8h8M8 12h8M8 16h5" />
        </>
      ) : name === "account" ? (
        <>
          <circle cx="12" cy="8" r="3.5" />
          <path d="M5 21v-2a7 7 0 0 1 14 0v2" />
        </>
      ) : name === "back" ? (
        <path d="m14 5-7 7 7 7" />
      ) : (
        <>
          <path d="M13 5H6a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-7" />
          <path d="m16 3 5 5M10 14l1-4 7-7 3 3-7 7-4 1Z" />
        </>
      )}
    </svg>
  );
}
