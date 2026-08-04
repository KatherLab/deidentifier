import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { Ref } from 'vue'

/**
 * Minimal popover/menu state: an open flag plus dismissal on outside
 * mousedown and Escape. `container` must wrap BOTH the trigger button and the
 * popover content, so clicks inside either never dismiss.
 */
export function usePopover(container: Ref<HTMLElement | null>) {
  const open = ref(false)

  function toggle(): void {
    open.value = !open.value
  }

  function close(): void {
    open.value = false
  }

  function onMousedown(event: MouseEvent): void {
    if (!open.value) return
    if (event.target instanceof Node && container.value?.contains(event.target)) return
    close()
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') close()
  }

  onMounted(() => {
    document.addEventListener('mousedown', onMousedown)
    document.addEventListener('keydown', onKeydown)
  })

  onBeforeUnmount(() => {
    document.removeEventListener('mousedown', onMousedown)
    document.removeEventListener('keydown', onKeydown)
  })

  return { open, toggle, close }
}
