import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { TableInfo, ColumnInfo, ForeignKeyInfo } from './DatabaseManagement';

interface ERDiagramProps {
  tables: TableInfo[];
  foreignKeys: ForeignKeyInfo[];
  getTableColumns: (tableName: string) => ColumnInfo[];
}

function ERDiagram({ tables, foreignKeys, getTableColumns }: ERDiagramProps) {
  const cardWidth = 260;
  const cardHeaderHeight = 33;
  const cardPaddingBottom = 8;
  const rowHeight = 23;
  const maxFields = 999;
  const marginX = 32;
  const marginY = 28;
  const gapX = 120;
  const gapY = 30;
  const laneOffset = 36;
  const portOffset = 12;
  const portSpreadStep = 4;
  const [selectedConnectionId, setSelectedConnectionId] = useState<string | null>(null);
  const [measuredRowCenters, setMeasuredRowCenters] = useState<Record<string, number>>({});
  const diagramRef = useRef<HTMLDivElement | null>(null);

  const tableMeta = useMemo(() => {
    return tables.map((table) => {
      const columns = getTableColumns(table.table_name);
      const visibleColumns = columns.slice(0, maxFields);
      const height = cardHeaderHeight + visibleColumns.length * rowHeight + cardPaddingBottom;
      return {
        table,
        columns,
        visibleColumns,
        height
      };
    });
  }, [tables, getTableColumns]);

  const positions = useMemo(() => {
    const tableNames = tableMeta.map(item => item.table.table_name);
    const childrenByParent = new Map<string, Set<string>>();
    const inDegree = new Map<string, number>();
    const levelMap = new Map<string, number>();

    tableNames.forEach(name => {
      childrenByParent.set(name, new Set<string>());
      inDegree.set(name, 0);
      levelMap.set(name, 0);
    });

    foreignKeys.forEach(fk => {
      if (!childrenByParent.has(fk.referenced_table_name) || !childrenByParent.has(fk.table_name)) return;
      childrenByParent.get(fk.referenced_table_name)!.add(fk.table_name);
      inDegree.set(fk.table_name, (inDegree.get(fk.table_name) || 0) + 1);
    });

    const roots = tableNames.filter(name => (inDegree.get(name) || 0) === 0);
    const queue = [...roots];
    const visited = new Set<string>();

    while (queue.length > 0) {
      const current = queue.shift()!;
      visited.add(current);
      const baseLevel = levelMap.get(current) || 0;
      childrenByParent.get(current)?.forEach(child => {
        const nextLevel = Math.max(levelMap.get(child) || 0, baseLevel + 1);
        levelMap.set(child, nextLevel);
        if (!visited.has(child)) queue.push(child);
      });
    }

    const maxLevel = Math.max(0, ...Array.from(levelMap.values()));
    const levelCount = maxLevel + 1;
    const xByLevel = Array.from({ length: levelCount }, (_, level) => marginX + level * (cardWidth + gapX));
    const colHeights = Array.from({ length: levelCount }, () => marginY);
    const map = new Map<string, { x: number; y: number }>();

    const parentByChild = new Map<string, Set<string>>();
    tableNames.forEach(name => parentByChild.set(name, new Set<string>()));
    foreignKeys.forEach(fk => {
      if (parentByChild.has(fk.table_name) && childrenByParent.has(fk.referenced_table_name)) {
        parentByChild.get(fk.table_name)!.add(fk.referenced_table_name);
      }
    });

    const metaByName = new Map(tableMeta.map(meta => [meta.table.table_name, meta]));
    const levels: string[][] = Array.from({ length: levelCount }, () => []);
    tableNames.forEach(name => {
      const lvl = levelMap.get(name) || 0;
      levels[lvl].push(name);
    });

    // 初始顺序：按度数和高度，给后续迭代一个更好的起点
    levels.forEach(names => {
      names.sort((a, b) => {
        const da = (childrenByParent.get(a)?.size || 0) + (parentByChild.get(a)?.size || 0);
        const db = (childrenByParent.get(b)?.size || 0) + (parentByChild.get(b)?.size || 0);
        if (da !== db) return db - da;
        return (metaByName.get(b)?.height || 0) - (metaByName.get(a)?.height || 0);
      });
    });

    const buildOrderMap = (names: string[]) => {
      const order = new Map<string, number>();
      names.forEach((name, i) => order.set(name, i));
      return order;
    };

    const barycentricSort = (
      currentLevel: string[],
      neighborLevelOrder: Map<string, number>,
      getNeighbors: (name: string) => Set<string> | undefined
    ) => {
      currentLevel.sort((a, b) => {
        const neighborsA = Array.from(getNeighbors(a) || []).filter(n => neighborLevelOrder.has(n));
        const neighborsB = Array.from(getNeighbors(b) || []).filter(n => neighborLevelOrder.has(n));

        const centerA = neighborsA.length
          ? neighborsA.reduce((sum, n) => sum + (neighborLevelOrder.get(n) || 0), 0) / neighborsA.length
          : Number.MAX_SAFE_INTEGER;
        const centerB = neighborsB.length
          ? neighborsB.reduce((sum, n) => sum + (neighborLevelOrder.get(n) || 0), 0) / neighborsB.length
          : Number.MAX_SAFE_INTEGER;

        if (centerA !== centerB) return centerA - centerB;
        return (metaByName.get(b)?.height || 0) - (metaByName.get(a)?.height || 0);
      });
    };

    // 两轮 sweep：减少跨层连线交叉
    for (let iter = 0; iter < 2; iter += 1) {
      for (let level = 1; level < levelCount; level += 1) {
        const leftOrder = buildOrderMap(levels[level - 1]);
        barycentricSort(levels[level], leftOrder, (name) => parentByChild.get(name));
      }
      for (let level = levelCount - 2; level >= 0; level -= 1) {
        const rightOrder = buildOrderMap(levels[level + 1]);
        barycentricSort(levels[level], rightOrder, (name) => childrenByParent.get(name));
      }
    }

    for (let level = 0; level < levelCount; level += 1) {
      levels[level].forEach(name => {
        const meta = metaByName.get(name);
        if (!meta) return;
        const x = xByLevel[level];
        const y = colHeights[level];
        map.set(name, { x, y });
        colHeights[level] += meta.height + gapY;
      });
    }

    return {
      map,
      width: xByLevel[xByLevel.length - 1] + cardWidth + marginX,
      height: Math.max(...colHeights) + marginY
    };
  }, [tableMeta, foreignKeys]);

  useLayoutEffect(() => {
    const container = diagramRef.current;
    if (!container) return;

    const computeRowCenters = () => {
      const containerRect = container.getBoundingClientRect();
      const nextCenters: Record<string, number> = {};
      const rowElements = container.querySelectorAll<HTMLElement>('.er-column[data-row-key]');

      rowElements.forEach((row) => {
        const rowKey = row.dataset.rowKey;
        if (!rowKey) return;
        const rect = row.getBoundingClientRect();
        nextCenters[rowKey] = rect.top - containerRect.top + rect.height / 2;
      });

      setMeasuredRowCenters((prev) => {
        const prevKeys = Object.keys(prev);
        const nextKeys = Object.keys(nextCenters);
        if (prevKeys.length !== nextKeys.length) return nextCenters;
        for (const key of nextKeys) {
          if (Math.abs((prev[key] || 0) - nextCenters[key]) > 0.2) return nextCenters;
        }
        return prev;
      });
    };

    computeRowCenters();
    const rafId = window.requestAnimationFrame(computeRowCenters);
    window.addEventListener('resize', computeRowCenters);

    return () => {
      window.cancelAnimationFrame(rafId);
      window.removeEventListener('resize', computeRowCenters);
    };
  }, [positions, tableMeta, selectedConnectionId]);

  const getRowCenterY = (tableName: string, columnName: string) => {
    const rowKey = `${tableName}.${columnName}`;
    const measured = measuredRowCenters[rowKey];
    if (typeof measured === 'number') {
      return measured;
    }

    const pos = positions.map.get(tableName);
    const meta = tableMeta.find(t => t.table.table_name === tableName);
    if (!pos || !meta) return 0;
    const index = Math.max(0, meta.visibleColumns.findIndex(c => c.column_name === columnName));
    return pos.y + cardHeaderHeight + index * rowHeight + rowHeight / 2;
  };

  const connections = useMemo(() => {
    const pairCounts = new Map<string, number>();

    const rawConnections = foreignKeys
      .map((fk, index) => {
        const parent = positions.map.get(fk.referenced_table_name);
        const child = positions.map.get(fk.table_name);
        if (!parent || !child) return null;

        const parentMeta = tableMeta.find(item => item.table.table_name === fk.referenced_table_name);
        const childMeta = tableMeta.find(item => item.table.table_name === fk.table_name);
        if (!parentMeta || !childMeta) return null;

        const parentY = getRowCenterY(fk.referenced_table_name, fk.referenced_column_name);
        const childY = getRowCenterY(fk.table_name, fk.column_name);
        const pairKey = [fk.table_name, fk.referenced_table_name].sort().join('::');
        const laneIndex = pairCounts.get(pairKey) || 0;
        pairCounts.set(pairKey, laneIndex + 1);
        const laneShift = laneIndex * 10;

        const childOnRight = child.x >= parent.x;

        let startX = 0;
        let startY = 0;
        let endX = 0;
        let endY = 0;
        let bend1X = 0;
        let bend1Y = 0;
        let bend2X = 0;
        let bend2Y = 0;
        startX = childOnRight ? parent.x + cardWidth : parent.x;
        endX = childOnRight ? child.x : child.x + cardWidth;
        // 起点/终点严格贴合字段行中心
        startY = parentY;
        endY = childY;

        const clearHorizontalGap = childOnRight
          ? child.x - (parent.x + cardWidth)
          : parent.x - (child.x + cardWidth);
        const routeX = clearHorizontalGap > laneOffset * 2
          ? (startX + endX) / 2 + (childOnRight ? laneShift : -laneShift)
          : (childOnRight
              ? Math.max(parent.x + cardWidth, child.x + cardWidth) + laneOffset + laneShift
              : Math.min(parent.x, child.x) - laneOffset - laneShift);

        bend1X = routeX;
        bend1Y = startY;
        bend2X = routeX;
        bend2Y = endY;

        const endSideDirection = childOnRight ? -1 : 1;
        const pathD = [
          `M ${startX} ${startY}`,
          `L ${startX + (bend1X > startX ? portOffset : bend1X < startX ? -portOffset : 0)} ${startY + (bend1Y > startY ? portOffset : bend1Y < startY ? -portOffset : 0)}`,
          `L ${bend1X} ${bend1Y}`,
          `L ${bend2X} ${bend2Y}`,
          `L ${endX + endSideDirection * portOffset} ${endY + (bend2Y > endY ? -portOffset : bend2Y < endY ? portOffset : 0)}`,
          `L ${endX} ${endY}`
        ].join(' ');

        const approachX = endX - endSideDirection * portOffset;
        const arrowX = routeX;
        const arrowY = (startY + endY) / 2;
        const arrowAngle = endY >= startY ? 90 : -90;

        return {
          id: `${fk.id || index}-${fk.table_name}-${fk.column_name}`,
          fk,
          startX,
          startY,
          endX,
          endY,
          routeX,
          approachX,
          pathD,
          arrowX,
          arrowY,
          arrowAngle,
          parentTableName: fk.referenced_table_name,
          parentColumnName: fk.referenced_column_name,
          childTableName: fk.table_name,
          childColumnName: fk.column_name,
          endSideDirection
        };
      })
      .filter((item): item is {
        id: string;
        fk: ForeignKeyInfo;
        startX: number;
        startY: number;
        endX: number;
        endY: number;
        routeX: number;
        approachX: number;
        pathD: string;
        arrowX: number;
        arrowY: number;
        arrowAngle: number;
        parentTableName: string;
        parentColumnName: string;
        childTableName: string;
        childColumnName: string;
        endSideDirection: number;
      } => Boolean(item));

    // 二次分流：避免不同表对在同一垂直走廊重叠
    const corridorGroups = new Map<number, typeof rawConnections>();
    const corridorBucket = 18;
    rawConnections.forEach(conn => {
      const bucket = Math.round(conn.routeX / corridorBucket);
      if (!corridorGroups.has(bucket)) corridorGroups.set(bucket, []);
      corridorGroups.get(bucket)!.push(conn);
    });

    corridorGroups.forEach(group => {
      if (group.length <= 1) return;
      group.sort((a, b) => {
        const ac = (a.startY + a.endY) / 2;
        const bc = (b.startY + b.endY) / 2;
        return ac - bc;
      });

      const step = 12;
      const center = (group.length - 1) / 2;
      group.forEach((conn, i) => {
        const offset = (i - center) * step;
        const routeX = conn.routeX + offset;
        const bend1X = routeX;
        const bend2X = routeX;
        const pathD = [
          `M ${conn.startX} ${conn.startY}`,
          `L ${conn.startX + (bend1X > conn.startX ? portOffset : bend1X < conn.startX ? -portOffset : 0)} ${conn.startY}`,
          `L ${bend1X} ${conn.startY}`,
          `L ${bend2X} ${conn.endY}`,
          `L ${conn.endX + conn.endSideDirection * portOffset} ${conn.endY}`,
          `L ${conn.endX} ${conn.endY}`
        ].join(' ');

        conn.pathD = pathD;
        conn.approachX = conn.endX - conn.endSideDirection * portOffset;
        conn.arrowX = routeX;
        conn.arrowY = (conn.startY + conn.endY) / 2;
        conn.arrowAngle = conn.endY >= conn.startY ? 90 : -90;
      });
    });

    return rawConnections;
  }, [foreignKeys, positions, tableMeta, portSpreadStep, measuredRowCenters]);

  const selectedConnection = useMemo(
    () => connections.find(conn => conn.id === selectedConnectionId) || null,
    [connections, selectedConnectionId]
  );

  const isHighlightedRow = (tableName: string, columnName: string) => {
    if (!selectedConnection) return false;
    return (
      (selectedConnection.parentTableName === tableName && selectedConnection.parentColumnName === columnName) ||
      (selectedConnection.childTableName === tableName && selectedConnection.childColumnName === columnName)
    );
  };

  return (
    <div className="er-view">
      <h3>ER图 ({tables.length} 个表)</h3>
      <div className="er-diagram" style={{ minHeight: positions.height }} ref={diagramRef}>
        <svg
          className="er-connection-lines"
          width={positions.width}
          height={positions.height}
        >
          <defs>
            <marker
              id="erOneMarker"
              markerWidth="10"
              markerHeight="10"
              refX="5"
              refY="5"
              orient="auto-start-reverse"
              markerUnits="strokeWidth"
            >
              <line x1="5" y1="1" x2="5" y2="9" stroke="#555555" strokeWidth="1.6" />
            </marker>
            <marker
              id="erOneMarkerActive"
              markerWidth="10"
              markerHeight="10"
              refX="5"
              refY="5"
              orient="auto-start-reverse"
              markerUnits="strokeWidth"
            >
              <line x1="5" y1="1" x2="5" y2="9" stroke="#0b61d8" strokeWidth="1.8" />
            </marker>
            <marker
              id="erCrowFootMarker"
              markerWidth="14"
              markerHeight="14"
              refX="12"
              refY="7"
              orient="auto"
              markerUnits="strokeWidth"
            >
              <path d="M 1 7 L 12 2 M 1 7 L 12 7 M 1 7 L 12 12" stroke="#555555" strokeWidth="1.4" fill="none" />
            </marker>
            <marker
              id="erCrowFootMarkerActive"
              markerWidth="14"
              markerHeight="14"
              refX="12"
              refY="7"
              orient="auto"
              markerUnits="strokeWidth"
            >
              <path d="M 1 7 L 12 2 M 1 7 L 12 7 M 1 7 L 12 12" stroke="#0b61d8" strokeWidth="1.8" fill="none" />
            </marker>
          </defs>
          {connections.map(conn => (
            <g key={conn.id}>
              <path
                d={conn.pathD}
                stroke="#555555"
                strokeWidth="1.6"
                fill="none"
                markerStart={`url(#${selectedConnectionId === conn.id ? 'erOneMarkerActive' : 'erOneMarker'})`}
                markerEnd={`url(#${selectedConnectionId === conn.id ? 'erCrowFootMarkerActive' : 'erCrowFootMarker'})`}
                onClick={() => setSelectedConnectionId(prev => (prev === conn.id ? null : conn.id))}
                className="er-curve-line"
                style={{
                  cursor: 'pointer',
                  opacity: selectedConnectionId && selectedConnectionId !== conn.id ? 0.25 : 1,
                  stroke: selectedConnectionId === conn.id ? '#0b61d8' : '#555555',
                  strokeWidth: selectedConnectionId === conn.id ? 2.2 : 1.6
                }}
              />
            </g>
          ))}
        </svg>

        <div className="er-tables-layer" style={{ width: positions.width, minHeight: positions.height }}>
          {tableMeta.map(({ table, visibleColumns, columns, height }) => {
            const position = positions.map.get(table.table_name);
            if (!position) return null;
            return (
            <div
              key={table.id}
              className="er-table"
              style={{
                left: `${position.x}px`,
                top: `${position.y}px`,
                width: cardWidth,
                height
              }}
            >
              <div className="er-table-header">
                <span className="er-table-name">{table.table_name}</span>
              </div>
              <div className="er-columns">
                {visibleColumns.map(col => (
                  <div
                    key={col.id}
                    data-row-key={`${table.table_name}.${col.column_name}`}
                    className={`er-column ${col.column_key === 'PRI' ? 'primary-key' : ''} ${isHighlightedRow(table.table_name, col.column_name) ? 'connection-highlight' : ''}`}
                  >
                    <span className="er-column-name">
                      {col.column_key === 'PRI' && <span className="er-key-tag">PK</span>}
                      {col.column_name}
                    </span>
                    <span className="er-column-type">{col.data_type}</span>
                  </div>
                ))}
                {columns.length > maxFields && (
                  <div className="er-more-columns">
                    ... 还有 {columns.length - maxFields} 个字段
                  </div>
                )}
              </div>
            </div>
          );
          })}
        </div>
      </div>
    </div>
  );
}

export default ERDiagram;
