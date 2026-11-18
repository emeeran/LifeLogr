/**
 * Viewport-relative pixel coordinates of the caret at `pos` in a textarea.
 *
 * Textareas don't expose caret x/y, so we clone the text into a hidden mirror
 * <div> that reproduces the textarea's wrapping, mark the caret position with a
 * <span>, and read its offset. Used to anchor the inline #tag popover.
 */
export function getCaretCoordinates(
  el: HTMLTextAreaElement,
  pos: number,
): { x: number; y: number } {
  const style = window.getComputedStyle(el)
  const mirror = document.createElement('div')
  const marker = document.createElement('span')
  Object.assign(mirror.style, {
    position: 'absolute',
    top: '0',
    left: '-9999px',
    visibility: 'hidden',
    whiteSpace: 'pre-wrap',
    wordWrap: 'break-word',
    width: el.clientWidth + 'px',
    fontFamily: style.fontFamily,
    fontSize: style.fontSize,
    fontWeight: style.fontWeight,
    lineHeight: style.lineHeight,
    letterSpacing: style.letterSpacing,
    paddingTop: style.paddingTop,
    paddingRight: style.paddingRight,
    paddingBottom: style.paddingBottom,
    paddingLeft: style.paddingLeft,
    borderTopWidth: style.borderTopWidth,
    borderLeftWidth: style.borderLeftWidth,
    boxSizing: style.boxSizing,
  } as Partial<CSSStyleDeclaration>)
  marker.textContent = el.value.slice(pos) || '​'
  mirror.textContent = el.value.slice(0, pos)
  mirror.appendChild(marker)
  document.body.appendChild(mirror)
  const mRect = mirror.getBoundingClientRect()
  const kRect = marker.getBoundingClientRect()
  const taRect = el.getBoundingClientRect()
  const x = taRect.left + (kRect.left - mRect.left)
  const y =
    taRect.top + (kRect.top - mRect.top) + parseFloat(style.lineHeight || '16')
  mirror.remove()
  return { x, y }
}
