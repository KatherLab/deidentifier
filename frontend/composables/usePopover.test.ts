import { describe, expect, it } from 'vitest'
import { defineComponent, h, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { usePopover } from '@/composables/usePopover'

/**
 * The composable registers document-level listeners in onMounted, so it needs
 * a real component instance and a container element in the document. The
 * returned refs are captured from setup() directly (not via `expose`, which
 * would unwrap them).
 */
function mountPopover() {
  let popover!: ReturnType<typeof usePopover>
  const host = defineComponent({
    setup() {
      const container = ref<HTMLElement | null>(null)
      popover = usePopover(container)
      return () =>
        h('div', { ref: container }, [
          h('button', { id: 'trigger', onClick: popover.toggle }, 'toggle'),
          popover.open.value ? h('div', { id: 'panel' }, 'content') : null,
        ])
    },
  })
  const wrapper = mount(host, { attachTo: document.body })
  return { wrapper, popover }
}

describe('usePopover', () => {
  it('toggles and closes', () => {
    const { wrapper, popover } = mountPopover()

    expect(popover.open.value).toBe(false)
    popover.toggle()
    expect(popover.open.value).toBe(true)
    popover.close()
    expect(popover.open.value).toBe(false)

    wrapper.unmount()
  })

  it('stays open for a mousedown inside the container', async () => {
    const { wrapper, popover } = mountPopover()
    popover.toggle()
    await wrapper.vm.$nextTick()

    wrapper.find('#panel').element.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))

    expect(popover.open.value).toBe(true)
    wrapper.unmount()
  })

  it('closes on an outside mousedown', () => {
    const { wrapper, popover } = mountPopover()
    popover.toggle()

    document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))

    expect(popover.open.value).toBe(false)
    wrapper.unmount()
  })

  it('closes on Escape', () => {
    const { wrapper, popover } = mountPopover()
    popover.toggle()

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))

    expect(popover.open.value).toBe(false)
    wrapper.unmount()
  })

  it('detaches its listeners on unmount', () => {
    const { wrapper, popover } = mountPopover()
    popover.toggle()
    wrapper.unmount()

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))

    // Still open: the handler is gone, so nothing reacted to the key.
    expect(popover.open.value).toBe(true)
  })
})
