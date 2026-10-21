import { changeTaskStatusAction } from '../../actions'
import type { Status } from '@/lib/types'

const STATUSES: Status[] = ['todo', 'doing', 'done']

// Per-task status control: a tiny form that submits the new status via a Server Action.
export default function TaskStatusControl({
  boardId,
  taskId,
  status,
}: {
  boardId: string
  taskId: string
  status: Status
}) {
  return (
    <form action={changeTaskStatusAction} className="inline-form">
      <input type="hidden" name="boardId" value={boardId} />
      <input type="hidden" name="taskId" value={taskId} />
      <select name="status" defaultValue={status} aria-label="Task status">
        {STATUSES.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
      <button className="ghost" type="submit">
        Update
      </button>
    </form>
  )
}
