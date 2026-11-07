import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import FolderMovePicker, { type MoveFolderOption } from './FolderMovePicker.vue'

// Work (1) > Projects (2) > Archive (3); Personal (4) is a root sibling.
const FOLDERS: MoveFolderOption[] = [
  { id: 1, name: 'Work', parent_id: null },
  { id: 2, name: 'Projects', parent_id: 1 },
  { id: 3, name: 'Archive', parent_id: 2 },
  { id: 4, name: 'Personal', parent_id: null },
]

async function open(props: InstanceType<typeof FolderMovePicker>['$props']) {
  const wrapper = mount(FolderMovePicker, { props })
  await wrapper.find('.move-trigger').trigger('click')
  return wrapper
}

describe('FolderMovePicker', () => {
  it('excludes the folder itself and its descendants', async () => {
    const wrapper = await open({ folderId: 1, parentId: null, folders: FOLDERS })
    const labels = wrapper.findAll('.move-option').map((b) => b.text())
    expect(labels).toEqual(['Top level', 'Personal'])
    expect(wrapper.find('[aria-checked="true"]').text()).toBe('Top level')
    wrapper.unmount()
  })

  it('offers the parent and unrelated notebooks for a nested folder', async () => {
    const wrapper = await open({
      folderId: 2,
      parentId: 1,
      folders: FOLDERS,
    })
    const labels = wrapper.findAll('.move-option').map((b) => b.text())
    expect(labels).toEqual(['Top level', 'Personal', 'Work'])
    expect(wrapper.find('[aria-checked="true"]').text()).toBe('Work')
    wrapper.unmount()
  })

  it('emits the chosen parent', async () => {
    const wrapper = await open({ folderId: 1, parentId: null, folders: FOLDERS })
    const personal = wrapper
      .findAll('.move-option')
      .find((b) => b.text() === 'Personal')
    await personal!.trigger('click')
    expect(wrapper.emitted('move')?.[0]).toEqual([4])
    expect(wrapper.find('.move-popover').exists()).toBe(false)
    wrapper.unmount()
  })

  it('emits null for Top level', async () => {
    const wrapper = await open({ folderId: 3, parentId: 2, folders: FOLDERS })
    const top = wrapper.findAll('.move-option')[0]
    await top.trigger('click')
    expect(wrapper.emitted('move')?.[0]).toEqual([null])
    wrapper.unmount()
  })

  it('says so when there is nowhere to move to', async () => {
    const wrapper = await open({
      folderId: 1,
      parentId: null,
      folders: [FOLDERS[0], FOLDERS[1]],
    })
    expect(wrapper.find('.move-empty').exists()).toBe(true)
    wrapper.unmount()
  })
})
