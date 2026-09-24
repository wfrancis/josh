import { useCallback, useEffect, useRef, useState } from 'react'

const EMPTY = { items: [], next: null, status: 'idle', error: null, loadingMore: false }

// Pages through history, newest first.
// fetchPage(beforeId) -> Promise<{ items, next_before_id }>; beforeId is null
// for the first page. Passing a new fetchPage (new filters) starts over.
export default function useAuditFeed(fetchPage, { enabled = true } = {}) {
  const [feed, setFeed] = useState(EMPTY)
  const feedRef = useRef(EMPTY)
  const generationRef = useRef(0)
  const busyRef = useRef(false)

  const commit = useCallback((next) => {
    feedRef.current = next
    setFeed(next)
  }, [])

  // keepItems: a refresh keeps the list on screen until the new one arrives.
  const reload = useCallback(async ({ keepItems = false } = {}) => {
    const generation = ++generationRef.current
    busyRef.current = true
    commit({ ...feedRef.current, items: keepItems ? feedRef.current.items : [], next: keepItems ? feedRef.current.next : null, status: 'loading', error: null, loadingMore: false })
    try {
      const page = await fetchPage(null)
      if (generation !== generationRef.current) return
      commit({ items: page?.items || [], next: page?.next_before_id ?? null, status: 'ready', error: null, loadingMore: false })
    } catch (err) {
      if (generation !== generationRef.current) return
      commit({ ...feedRef.current, status: 'error', error: err, loadingMore: false })
    } finally {
      if (generation === generationRef.current) busyRef.current = false
    }
  }, [fetchPage, commit])

  const loadMore = useCallback(async () => {
    const current = feedRef.current
    if (busyRef.current || current.next == null || current.status !== 'ready') return
    const generation = generationRef.current
    busyRef.current = true
    commit({ ...current, loadingMore: true, error: null })
    try {
      const page = await fetchPage(current.next)
      if (generation !== generationRef.current) return
      const seen = new Set(feedRef.current.items.map(item => item.id))
      const added = (page?.items || []).filter(item => !seen.has(item.id))
      commit({ ...feedRef.current, items: [...feedRef.current.items, ...added], next: page?.next_before_id ?? null, loadingMore: false })
    } catch (err) {
      if (generation !== generationRef.current) return
      commit({ ...feedRef.current, loadingMore: false, error: err })
    } finally {
      if (generation === generationRef.current) busyRef.current = false
    }
  }, [fetchPage, commit])

  useEffect(() => {
    if (!enabled) return undefined
    reload()
    return () => { generationRef.current += 1; busyRef.current = false }
  }, [enabled, reload])

  return {
    items: feed.items,
    next: feed.next,
    hasMore: feed.next != null,
    loading: feed.status === 'loading' || feed.status === 'idle',
    loadingMore: feed.loadingMore,
    ready: feed.status === 'ready',
    error: feed.error,
    reload,
    loadMore,
  }
}

// Plain-English text for a failed history request.
export function historyErrorText(err) {
  if (!err) return ''
  if (err.status === 404) return "History isn't available here yet."
  if (err.status === 400 && err.message) return err.message
  if (err.status >= 500) return 'The server had a problem loading history. Try again in a moment.'
  if (!err.status) return "Couldn't reach the server. Check your connection, then try again."
  return err.message || "History couldn't be loaded."
}
