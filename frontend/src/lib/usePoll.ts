import { useEffect, useRef } from 'react'

/** Run `fn` now and every `ms` while `enabled`. Skips a tick if the previous call is still in flight. */
export function usePoll(fn: () => Promise<unknown>, ms: number, enabled = true) {
  const fnRef = useRef(fn)
  fnRef.current = fn
  useEffect(() => {
    if (!enabled) return
    let alive = true
    let busy = false
    const tick = async () => {
      if (busy || !alive) return
      busy = true
      try {
        await fnRef.current()
      } catch {
        /* the caller surfaces errors; keep polling */
      } finally {
        busy = false
      }
    }
    void tick()
    const id = setInterval(tick, ms)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [ms, enabled])
}
