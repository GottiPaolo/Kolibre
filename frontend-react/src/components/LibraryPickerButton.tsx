import { Library as LibraryIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import type { Library } from '@/types/library'

// Selettore libreria riusabile (Importa, Impostazioni ▸ Librerie e ▸ Operazioni
// di massa) — stesso pattern
// del picker libreria di StatisticsPage.tsx (DropdownMenu con Button
// trigger), qui parametrizzato perché entrambe le tab ne hanno bisogno con
// semantiche diverse (destinazione import vs. libreria su cui operare).
export function LibraryPickerButton({
  libraries,
  value,
  onChange,
  size = 'sm',
}: {
  libraries: Library[]
  value: Library | undefined
  onChange: (id: number) => void
  size?: 'sm' | 'default'
}) {
  if (libraries.length === 0) return null

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size={size}>
          <LibraryIcon className="size-3.5" />
          {value?.name ?? '—'}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        {libraries.map((lib) => (
          <DropdownMenuItem key={lib.id} onSelect={() => onChange(lib.id)}>
            {lib.name}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
