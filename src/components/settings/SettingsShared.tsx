import { useEffect, useRef, useState, type ReactNode } from "react";
import { X, AlertTriangle, Check } from "lucide-react";

export function SettingSwitch({
  label,
  checked,
  onChange,
  disabled = false,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      className="stg-switch"
      role="switch"
      aria-label={label}
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
    >
      <span />
    </button>
  );
}
export function SettingsDialog({
  open,
  identity,
  title,
  onClose,
  children,
}: {
  open: boolean;
  identity: string;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (open && !dialog?.open) dialog?.showModal();
    if (!open && dialog?.open) dialog.close();
    if (open)
      requestAnimationFrame(() =>
        dialog
          ?.querySelector<HTMLElement>(
            '[autofocus], input:not([type="checkbox"]), select, button',
          )
          ?.focus(),
      );
    const previous = document.body.style.overflow;
    if (open) document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open, identity]);
  return (
    <dialog
      ref={ref}
      className="stg-dialog"
      aria-labelledby="settings-dialog-title"
      onCancel={onClose}
      onClose={onClose}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
      onKeyDown={(event) => {
        if (event.key !== "Tab") return;
        const controls = [
          ...(ref.current?.querySelectorAll<HTMLElement>(
            "a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])",
          ) ?? []),
        ].filter((element) => element.getClientRects().length > 0);
        const first = controls[0],
          last = controls.at(-1);
        if (event.shiftKey && document.activeElement === first && last) {
          event.preventDefault();
          last.focus();
        } else if (
          !event.shiftKey &&
          document.activeElement === last &&
          first
        ) {
          event.preventDefault();
          first.focus();
        }
      }}
    >
      <div className="stg-dialog-inner">
        <header>
          <h2 id="settings-dialog-title">{title}</h2>
          <button
            className="icon-button"
            onClick={onClose}
            aria-label="بستن پنجره تنظیمات"
          >
            <X size={20} />
          </button>
        </header>
        {children}
      </div>
    </dialog>
  );
}
export function ConfirmSettingAction({
  description,
  details,
  button,
  onConfirm,
  onCancel,
}: {
  description: string;
  details?: ReactNode;
  button: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const [acknowledged, setAcknowledged] = useState(false);
  return (
    <div className="stg-confirm">
      <span className="stg-confirm-icon">
        <AlertTriangle size={25} />
      </span>
      <p>{description}</p>
      {details}
      <label className="stg-ack">
        <input
          type="checkbox"
          checked={acknowledged}
          onChange={(event) => setAcknowledged(event.target.checked)}
        />
        تغییرات بالا را برای سناریوی ماک تأیید می‌کنم.
      </label>
      <div className="stg-modal-actions">
        <button
          className="stg-danger-button"
          disabled={!acknowledged}
          onClick={onConfirm}
        >
          <Check size={14} />
          {button}
        </button>
        <button className="stg-secondary-button" onClick={onCancel}>
          انصراف
        </button>
      </div>
    </div>
  );
}
