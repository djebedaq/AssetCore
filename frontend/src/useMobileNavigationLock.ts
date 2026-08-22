import { useEffect } from 'react'

export function useMobileNavigationLock(open: boolean) {
  useEffect(() => {
    if (!open) return

    const body = document.body
    const root = document.documentElement
    const scrollX = window.scrollX
    const scrollY = window.scrollY
    const previous = {
      overflow: body.style.overflow,
      position: body.style.position,
      top: body.style.top,
      left: body.style.left,
      width: body.style.width,
    }

    root.classList.add('mobile-navigation-open')
    body.style.overflow = 'hidden'
    body.style.position = 'fixed'
    body.style.top = `-${scrollY}px`
    body.style.left = `-${scrollX}px`
    body.style.width = '100%'

    return () => {
      root.classList.remove('mobile-navigation-open')
      body.style.overflow = previous.overflow
      body.style.position = previous.position
      body.style.top = previous.top
      body.style.left = previous.left
      body.style.width = previous.width
      window.scrollTo(scrollX, scrollY)
      window.requestAnimationFrame(() => window.scrollTo(scrollX, scrollY))
    }
  }, [open])
}
