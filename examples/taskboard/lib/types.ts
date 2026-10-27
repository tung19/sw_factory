export type Status = 'todo' | 'doing' | 'done'

export interface User {
  id: string
  email: string
}

export interface Account {
  id: string
  email: string
  passwordHash: string
}

export interface Board {
  id: string
  name: string
  ownerId: string
}

export interface Task {
  id: string
  boardId: string
  title: string
  status: Status
}
