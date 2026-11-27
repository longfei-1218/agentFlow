import { useEffect, useState } from "react";
import { X } from "lucide-react";

interface Props {
  open: boolean;
  title: string;
  description?: string;
  busy?: boolean;
  confirmText?: string;
  onClose: () => void;
  onConfirm: (name: string, note: string) => void;
}

/**
 * 发布弹窗：版本名必填，用于版本时间线与质量归因时区分「这一版是什么场景」；
 * 发布说明可留空，适合补充改动细节。
 */
export function PublishDialog({ open, title, description, busy, confirmText, onClose, onConfirm }: Props) {
  const [name, setName] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    if (open) {
      setName("");
      setNote("");
    }
  }, [open]);

  if (!open) return null;

  const trimmedName = name.trim();
  const canSubmit = Boolean(trimmedName) && !busy;

  return (
    <div className="fixed inset-0 z-40 bg-black/30 flex items-center justify-center" onClick={onClose}>
      <div
        className="card w-[440px] p-4"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="flex items-start justify-between">
          <div>
            <div className="text-[14px] font-semibold">{title}</div>
            {description && <div className="text-[11px] text-ink-3 mt-1">{description}</div>}
          </div>
          <button className="text-ink-3 hover:text-ink" onClick={onClose} aria-label="关闭">
            <X size={15} />
          </button>
        </div>

        <label className="block text-[12px] text-ink-2 mt-4 mb-1">
          版本名 <span className="text-danger">*</span>
        </label>
        <input
          className="field w-full text-[12px]"
          placeholder="例如：v2 换成 few-shot 提示词"
          value={name}
          maxLength={40}
          autoFocus
          onChange={(event) => setName(event.target.value)}
        />
        {!trimmedName && <div className="text-[11px] text-ink-3 mt-1">版本名必填，最多 40 字。</div>}

        <label className="block text-[12px] text-ink-2 mt-3 mb-1">发布说明（可留空）</label>
        <textarea
          className="field w-full h-[66px] resize-none text-[12px]"
          placeholder="例如：把分类提示词换成 few-shot 版本"
          value={note}
          maxLength={200}
          onChange={(event) => setNote(event.target.value)}
        />
        <div className="text-[11px] text-ink-3 mt-1">
          不检查内容是否有改动：同一配置也可以再发一版。发布会生成不可变快照，并记录配置指纹、工具指纹与代码
          commit；运行仍使用当前保存的配置。
        </div>

        <div className="flex justify-end gap-2 mt-4">
          <button className="btn" onClick={onClose} disabled={busy}>取消</button>
          <button
            className="btn-primary"
            onClick={() => onConfirm(trimmedName, note.trim())}
            disabled={!canSubmit}
          >
            {busy ? "发布中…" : confirmText ?? "确认发布"}
          </button>
        </div>
      </div>
    </div>
  );
}
