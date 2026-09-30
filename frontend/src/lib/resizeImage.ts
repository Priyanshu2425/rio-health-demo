/** Longest-side cap for uploads: enough for handwriting, small enough for a phone on 4G. */
export const MAX_UPLOAD_SIDE = 1600

/** Target size given the source size, keeping aspect ratio and never upscaling. */
export function fitWithin(width: number, height: number, max = MAX_UPLOAD_SIDE): { width: number; height: number } {
  const scale = Math.min(1, max / Math.max(width, height))
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) }
}

/**
 * Resize a photo client-side to ≤ 1600 px on the longest side and re-encode as JPEG.
 * EXIF orientation is applied by createImageBitmap, so phone photos stay upright.
 * Falls back to the original file if the browser can't decode it (the server then decides).
 */
export async function resizeImage(file: Blob, max = MAX_UPLOAD_SIDE, quality = 0.85): Promise<Blob> {
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' })
    const { width, height } = fitWithin(bitmap.width, bitmap.height, max)
    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext('2d')
    if (!ctx) return file
    // JPEG has no alpha: paint white first so transparent PNGs don't turn black.
    ctx.fillStyle = '#fff'
    ctx.fillRect(0, 0, width, height)
    ctx.drawImage(bitmap, 0, 0, width, height)
    bitmap.close()
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality))
    return blob ?? file
  } catch {
    return file
  }
}
