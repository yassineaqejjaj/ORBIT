import * as React from "react";

import { cn } from "@/lib/utils";

export interface TableProps extends React.TableHTMLAttributes<HTMLTableElement> {
  /** Classes for the scroll container. Give it a max height to get a sticky header. */
  containerClassName?: string;
  /** Tighter row height for dense data. */
  dense?: boolean;
}

const DenseContext = React.createContext(false);

/** Scrollable table; <TableHeader> is sticky inside the container. */
export const Table = React.forwardRef<HTMLTableElement, TableProps>(
  ({ className, containerClassName, dense = false, ...props }, ref) => (
    <DenseContext.Provider value={dense}>
      <div className={cn("relative w-full overflow-auto", containerClassName)}>
        <table ref={ref} className={cn("w-full caption-bottom border-separate border-spacing-0 text-sm", className)} {...props} />
      </div>
    </DenseContext.Provider>
  ),
);
Table.displayName = "Table";

export const TableHeader = React.forwardRef<HTMLTableSectionElement, React.HTMLAttributes<HTMLTableSectionElement>>(
  ({ className, ...props }, ref) => (
    <thead
      ref={ref}
      className={cn("sticky top-0 z-10 bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/80", className)}
      {...props}
    />
  ),
);
TableHeader.displayName = "TableHeader";

export const TableBody = React.forwardRef<HTMLTableSectionElement, React.HTMLAttributes<HTMLTableSectionElement>>(
  ({ className, ...props }, ref) => (
    <tbody ref={ref} className={cn("[&_tr:last-child>td]:border-b-0", className)} {...props} />
  ),
);
TableBody.displayName = "TableBody";

export const TableFooter = React.forwardRef<HTMLTableSectionElement, React.HTMLAttributes<HTMLTableSectionElement>>(
  ({ className, ...props }, ref) => (
    <tfoot ref={ref} className={cn("bg-muted/50 font-medium [&>tr>td]:border-t [&>tr>td]:border-border", className)} {...props} />
  ),
);
TableFooter.displayName = "TableFooter";

export interface TableRowProps extends React.HTMLAttributes<HTMLTableRowElement> {
  /** Hover + pointer affordance for clickable rows. */
  interactive?: boolean;
  selected?: boolean;
}

export const TableRow = React.forwardRef<HTMLTableRowElement, TableRowProps>(
  ({ className, interactive, selected, ...props }, ref) => (
    <tr
      ref={ref}
      data-state={selected ? "selected" : undefined}
      className={cn(
        "transition-colors data-[state=selected]:bg-brand-soft/60",
        interactive && "cursor-pointer hover:bg-muted/60 focus-visible:bg-muted/60 focus-visible:outline-none",
        className,
      )}
      {...props}
    />
  ),
);
TableRow.displayName = "TableRow";

export const TableHead = React.forwardRef<HTMLTableCellElement, React.ThHTMLAttributes<HTMLTableCellElement>>(
  ({ className, ...props }, ref) => {
    const dense = React.useContext(DenseContext);
    return (
      <th
        ref={ref}
        className={cn(
          "whitespace-nowrap border-b border-border px-3 text-left align-middle text-[11.5px] font-medium uppercase tracking-wide text-muted-foreground",
          dense ? "h-8" : "h-9",
          "first:pl-4 last:pr-4 [&:has([role=checkbox])]:w-10",
          className,
        )}
        {...props}
      />
    );
  },
);
TableHead.displayName = "TableHead";

export const TableCell = React.forwardRef<HTMLTableCellElement, React.TdHTMLAttributes<HTMLTableCellElement>>(
  ({ className, ...props }, ref) => {
    const dense = React.useContext(DenseContext);
    return (
      <td
        ref={ref}
        className={cn(
          "border-b border-border px-3 align-middle text-[13px]",
          dense ? "py-1.5" : "py-2.5",
          "first:pl-4 last:pr-4",
          className,
        )}
        {...props}
      />
    );
  },
);
TableCell.displayName = "TableCell";

export const TableCaption = React.forwardRef<HTMLTableCaptionElement, React.HTMLAttributes<HTMLTableCaptionElement>>(
  ({ className, ...props }, ref) => (
    <caption ref={ref} className={cn("mt-3 text-xs text-muted-foreground", className)} {...props} />
  ),
);
TableCaption.displayName = "TableCaption";

/** Full-width row for empty/loading states inside a table body. */
export function TableEmptyRow({ colSpan, children }: { colSpan: number; children: React.ReactNode }) {
  return (
    <tr>
      <td colSpan={colSpan} className="px-4 py-10 text-center text-sm text-muted-foreground">
        {children}
      </td>
    </tr>
  );
}
