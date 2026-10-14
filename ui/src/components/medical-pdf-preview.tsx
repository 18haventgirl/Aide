import { useEffect, useRef, useState } from 'react';
import type { PDFDocumentProxy } from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { Button } from './ui/button';

/** Render locally so embedded browsers do not need a native PDF viewer. */
export function MedicalPdfPreview({ url, filename }: { url: string; filename: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null);
  const [page, setPage] = useState(1);
  const [rendering, setRendering] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let disposed = false;
    let task: ReturnType<typeof import('pdfjs-dist')['getDocument']> | undefined;
    setDocument(null); setPage(1); setError(''); setRendering(true);
    void import('pdfjs-dist').then(async pdfjs => {
      if (disposed) return;
      pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
      const assets = `${import.meta.env.BASE_URL}pdfjs/`;
      task = pdfjs.getDocument({ url, cMapUrl: `${assets}cmaps/`, cMapPacked: true,
        standardFontDataUrl: `${assets}standard_fonts/`, wasmUrl: `${assets}wasm/`,
        isEvalSupported: false });
      const loaded = await task.promise;
      if (!disposed) setDocument(loaded);
    }).catch(() => { if (!disposed) { setError('预览未能加载，可下载原文件查看，或切换到文字核对。'); setRendering(false); } });
    return () => { disposed = true; if (task) void task.destroy(); };
  }, [url]);

  useEffect(() => {
    if (!document) return;
    let disposed = false;
    let task: ReturnType<Awaited<ReturnType<PDFDocumentProxy['getPage']>>['render']> | undefined;
    setRendering(true); setError('');
    void document.getPage(page).then(async pdfPage => {
      if (disposed || !canvas.current) return;
      const natural = pdfPage.getViewport({ scale: 1 });
      const scale = Math.min(1.5, 1600 / natural.width, Math.sqrt(4_000_000 / (natural.width * natural.height)));
      const viewport = pdfPage.getViewport({ scale });
      canvas.current.width = Math.ceil(viewport.width);
      canvas.current.height = Math.ceil(viewport.height);
      task = pdfPage.render({ canvas: canvas.current, viewport });
      await task.promise;
      if (!disposed) setRendering(false);
    }).catch(() => { if (!disposed) { setError('这一页未能显示，可下载原文件查看。'); setRendering(false); } });
    return () => { disposed = true; task?.cancel(); };
  }, [document, page]);

  return <div className="space-y-3" aria-label="PDF 原件预览" aria-busy={rendering}>
    <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
      <div className="flex items-center gap-2">
        <Button size="sm" variant="outline" disabled={!document || page <= 1 || rendering} onClick={() => setPage(value => value - 1)} aria-label="PDF 上一页">上一页</Button>
        <span aria-live="polite">{document ? `第 ${page} / ${document.numPages} 页` : '正在加载…'}</span>
        <Button size="sm" variant="outline" disabled={!document || page >= document.numPages || rendering} onClick={() => setPage(value => value + 1)} aria-label="PDF 下一页">下一页</Button>
      </div>
      <a href={url} download={filename} className="text-primary underline underline-offset-4">下载原文件</a>
    </div>
    {error && <p role="alert" className="text-sm text-amber-700">{error}</p>}
    {rendering && <p role="status" className="text-xs text-muted-foreground">正在显示第 {page} 页…</p>}
    <canvas ref={canvas} role="img" aria-label={`病历 PDF 第 ${page} 页`} className={`h-auto w-full rounded-lg border bg-white ${rendering || error ? 'hidden' : ''}`} />
  </div>;
}
