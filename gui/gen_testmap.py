#!/usr/bin/env python3
"""Generate a test battle map: 1300x1300 px with 50px border, 12x12 grid, 100 px per cell."""

from PIL import Image, ImageDraw

IMG_SIZE = 1300
BORDER = 50
GRID_START = BORDER
GRID_WIDTH = IMG_SIZE - 2 * BORDER  # 1200x1200
GRID_SIZE = 12
CELL_SIZE = GRID_WIDTH // GRID_SIZE  # 100 px per cell
OUTPUT_PATH = '/src/maps/TestGrid12x12.png'

# Create a white background image (with empty border)
img = Image.new('RGB', (IMG_SIZE, IMG_SIZE), color='white')
draw = ImageDraw.Draw(img)

# Draw grid lines (light gray) - interior only, with border
grid_color = (200, 200, 200)

# Vertical lines (inside the border, so all lines are detectable)
for col in range(GRID_SIZE + 1):
    x = GRID_START + col * CELL_SIZE
    draw.line([(x, GRID_START), (x, GRID_START + GRID_WIDTH)], fill=grid_color, width=1)

# Horizontal lines (inside the border, so all lines are detectable)
for row in range(GRID_SIZE + 1):
    y = GRID_START + row * CELL_SIZE
    draw.line([(GRID_START, y), (GRID_START + GRID_WIDTH, y)], fill=grid_color, width=1)

# Save as PNG
img.save(OUTPUT_PATH, 'PNG')
print(f"✓ Created test map: {OUTPUT_PATH}")
print(f"  Image size: {IMG_SIZE}x{IMG_SIZE} px")
print(f"  Border: {BORDER}px on all sides")
print(f"  Grid area: {GRID_WIDTH}x{GRID_WIDTH} px")
print(f"  Grid: {GRID_SIZE}x{GRID_SIZE} cells")
print(f"  Cell size: {CELL_SIZE}x{CELL_SIZE} px")
