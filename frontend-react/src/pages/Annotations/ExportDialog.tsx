import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useLingua } from '@/lib/i18n'

interface ExportDialogProps {
  onClose: () => void
  onExport: (format: 'md' | 'html', scope: 'single' | 'multi') => void
}

export function ExportDialog({ onClose, onExport }: ExportDialogProps) {
  const { t } = useLingua()
  const [format, setFormat] = useState<'md' | 'html'>('md')
  const [scope, setScope] = useState<'single' | 'multi'>('single')

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{t('annotations.export.dialogTitle')}</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1 text-[11.5px] font-medium text-muted-foreground">
            {t('annotations.export.formatLabel')}
            <Select value={format} onValueChange={(v) => setFormat(v as 'md' | 'html')}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="md">{t('annotations.export.formatMarkdown')}</SelectItem>
                <SelectItem value="html">{t('annotations.export.formatHtml')}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="flex flex-col gap-1 text-[11.5px] font-medium text-muted-foreground">
            {t('annotations.export.scopeLabel')}
            <Select value={scope} onValueChange={(v) => setScope(v as 'single' | 'multi')}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="single">{t('annotations.export.scopeSingle')}</SelectItem>
                <SelectItem value="multi">{t('annotations.export.scopeMulti')}</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={() => onExport(format, scope)}>{t('annotations.export.proceed')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
