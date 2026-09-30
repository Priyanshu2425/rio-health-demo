import { useEffect, useRef, useState } from 'react'

/** The prescription photo: a thumbnail in the review pane, a zoomable full view on click. */
export function RxImage({ src }: { src: string }) {
  const [open, setOpen] = useState(false)
  const [zoom, setZoom] = useState(1)
  const dialogRef = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const d = dialogRef.current
    if (!d) return
    if (open && !d.open) d.showModal()
    if (!open && d.open) d.close()
  }, [open])

  return (
    <aside className="rx-img">
      <button className="rx-thumb" onClick={() => (setZoom(1), setOpen(true))} aria-label="Open the prescription photo">
        <img src={src} alt="Prescription as uploaded" />
        <span className="rx-zoom-hint">Click to zoom</span>
      </button>
      <dialog ref={dialogRef} className="rx-dialog" onClose={() => setOpen(false)} onCancel={() => setOpen(false)}>
        <div className="rx-dialog-bar">
          <span>Prescription photo</span>
          <span className="rx-dialog-tools">
            {[1, 1.6, 2.4].map((z) => (
              <button
                key={z}
                className={`btn btn-sm${zoom === z ? ' btn-primary' : ''}`}
                onClick={() => setZoom(z)}
                aria-pressed={zoom === z}
              >
                {z === 1 ? 'Fit' : `${z}×`}
              </button>
            ))}
            <button className="btn btn-sm" onClick={() => setOpen(false)}>
              Close
            </button>
          </span>
        </div>
        <div className="rx-dialog-view">
          <img
            src={src}
            alt="Prescription, zoomed"
            style={{ width: `${zoom * 100}%` }}
            onClick={() => setZoom((z) => (z === 1 ? 1.6 : z === 1.6 ? 2.4 : 1))}
          />
        </div>
      </dialog>
    </aside>
  )
}
