import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { AlertTriangle, CheckCircle2, Info, X } from 'lucide-react';

type DialogKind = 'alert' | 'confirm';
type DialogIntent = 'info' | 'warning' | 'danger' | 'success';

interface DialogOptions {
  title?: string;
  confirmText?: string;
  cancelText?: string;
  intent?: DialogIntent;
}

interface DialogRequest extends DialogOptions {
  kind: DialogKind;
  message: string;
  resolve: (confirmed: boolean) => void;
}

interface DialogContextValue {
  /** 展示统一风格的确认弹窗，并返回用户是否确认。 */
  confirm: (message: string, options?: DialogOptions) => Promise<boolean>;
  /** 展示统一风格的信息弹窗，并等待用户关闭。 */
  alert: (message: string, options?: DialogOptions) => Promise<void>;
}

const DialogContext = createContext<DialogContextValue | null>(null);

/** 获取全局业务弹窗控制器，替代浏览器原生 alert/confirm。 */
export function useDialog(): DialogContextValue {
  const context = useContext(DialogContext);
  if (!context) {
    throw new Error('useDialog 必须在 DialogProvider 内部使用');
  }
  return context;
}

interface DialogProviderProps {
  children: ReactNode;
}

export function DialogProvider({ children }: DialogProviderProps) {
  const [request, setRequest] = useState<DialogRequest | null>(null);
  const confirmButtonRef = useRef<HTMLButtonElement | null>(null);

  const confirm = useCallback((message: string, options: DialogOptions = {}) => {
    return new Promise<boolean>((resolve) => {
      setRequest({ kind: 'confirm', message, resolve, ...options });
    });
  }, []);

  const alert = useCallback((message: string, options: DialogOptions = {}) => {
    return new Promise<void>((resolve) => {
      setRequest({
        kind: 'alert',
        message,
        resolve: () => resolve(),
        ...options,
      });
    });
  }, []);

  const closeDialog = useCallback((confirmed: boolean) => {
    if (!request) return;
    request.resolve(confirmed);
    setRequest(null);
  }, [request]);

  useEffect(() => {
    if (!request) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        closeDialog(false);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    confirmButtonRef.current?.focus();
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [closeDialog, request]);

  const intent = request?.intent || (request?.kind === 'confirm' ? 'warning' : 'info');
  const intentClasses = {
    info: {
      icon: 'border-blue-400/30 bg-blue-500/15 text-blue-300',
      button: 'bg-blue-600 hover:bg-blue-500 shadow-blue-500/20',
    },
    warning: {
      icon: 'border-amber-400/30 bg-amber-500/15 text-amber-300',
      button: 'bg-amber-600 hover:bg-amber-500 shadow-amber-500/20',
    },
    danger: {
      icon: 'border-rose-400/30 bg-rose-500/15 text-rose-300',
      button: 'bg-rose-600 hover:bg-rose-500 shadow-rose-500/20',
    },
    success: {
      icon: 'border-emerald-400/30 bg-emerald-500/15 text-emerald-300',
      button: 'bg-emerald-600 hover:bg-emerald-500 shadow-emerald-500/20',
    },
  }[intent];

  const icon = intent === 'danger' || intent === 'warning'
    ? <AlertTriangle className="h-5 w-5" />
    : intent === 'success'
      ? <CheckCircle2 className="h-5 w-5" />
      : <Info className="h-5 w-5" />;

  return (
    <DialogContext.Provider value={{ confirm, alert }}>
      {children}

      {request && (
        <div
          className="fixed inset-0 z-[120] flex items-center justify-center bg-slate-950/70 p-4 backdrop-blur-sm"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeDialog(false);
          }}
        >
          <div
            className="w-full max-w-lg overflow-hidden rounded-2xl border border-slate-700/80 bg-slate-900/95 shadow-2xl shadow-black/40"
            role="dialog"
            aria-modal="true"
            aria-labelledby="app-dialog-title"
            aria-describedby="app-dialog-message"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="flex items-start gap-3 border-b border-slate-700/70 px-5 py-4">
              <div className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border ${intentClasses.icon}`}>
                {icon}
              </div>
              <div className="min-w-0 flex-1">
                <h2 id="app-dialog-title" className="text-base font-bold text-slate-100">
                  {request.title || (request.kind === 'confirm' ? '请确认操作' : '提示')}
                </h2>
                <p id="app-dialog-message" className="mt-2 whitespace-pre-line text-sm leading-6 text-slate-300">
                  {request.message}
                </p>
              </div>
              <button
                type="button"
                aria-label="关闭弹窗"
                onClick={() => closeDialog(request.kind === 'alert')}
                className="rounded-lg p-1.5 text-slate-500 transition hover:bg-slate-800 hover:text-slate-200"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="flex justify-end gap-2 px-5 py-4">
              {request.kind === 'confirm' && (
                <button
                  type="button"
                  onClick={() => closeDialog(false)}
                  className="rounded-lg border border-slate-600 bg-slate-800 px-4 py-2 text-sm font-semibold text-slate-300 transition hover:bg-slate-700 hover:text-white"
                >
                  {request.cancelText || '取消'}
                </button>
              )}
              <button
                ref={confirmButtonRef}
                type="button"
                onClick={() => closeDialog(true)}
                className={`rounded-lg px-4 py-2 text-sm font-semibold text-white shadow-lg transition ${intentClasses.button}`}
              >
                {request.confirmText || (request.kind === 'confirm' ? '确定' : '知道了')}
              </button>
            </div>
          </div>
        </div>
      )}
    </DialogContext.Provider>
  );
}
