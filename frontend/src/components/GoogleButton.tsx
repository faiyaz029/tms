import { useEffect, useRef } from "react";

declare global { interface Window { google?: any } }

const CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined;

export default function GoogleButton({ onCredential }: { onCredential: (c: string) => void }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!CLIENT_ID) return;
    const init = () => {
      window.google?.accounts.id.initialize({ client_id: CLIENT_ID, callback: (r: { credential: string }) => onCredential(r.credential) });
      if (ref.current) window.google?.accounts.id.renderButton(ref.current, { theme: "outline", size: "large", width: 300, text: "continue_with" });
    };
    if (window.google) return init();
    const s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true;
    s.onload = init;
    document.head.appendChild(s);
  }, [onCredential]);

  if (!CLIENT_ID) {
    return <p className="rounded-lg border border-dashed border-amber-600 p-3 text-sm text-amber-700 dark:text-amber-400">
      Google login is off. Set VITE_GOOGLE_CLIENT_ID in frontend/.env to enable it.</p>;
  }
  return <div ref={ref} className="flex justify-center" />;
}
