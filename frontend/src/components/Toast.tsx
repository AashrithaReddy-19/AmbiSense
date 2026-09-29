import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";

export type ToastKind = "success" | "error" | "info" | "warning";
type ToastItem = { id: number; kind: ToastKind; message: string };
type ToastValue = { show: (message: string, kind?: ToastKind) => void };

const ToastContext = createContext<ToastValue>({ show: () => {} });

const ICONS: Record<ToastKind, typeof CheckCircle2> = { success: CheckCircle2, error: XCircle, info: Info, warning: AlertTriangle };

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const counter = useRef(0);
  const show = useCallback((message: string, kind: ToastKind = "info") => {
    const id = ++counter.current;
    setItems((old) => [...old, { id, kind, message }]);
    window.setTimeout(() => setItems((old) => old.filter((item) => item.id !== id)), 5000);
  }, []);
  const value = useMemo(() => ({ show }), [show]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-stack" role="status" aria-live="polite">
        {items.map((item) => {
          const Icon = ICONS[item.kind];
          return (
            <div className={`toast toast-${item.kind}`} key={item.id}>
              <Icon size={16} />
              <span>{item.message}</span>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
