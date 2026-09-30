# Figma Chat A.I+ — React/Vite recreation

Reference: Figma file `4pkb2wgr5w5toSxFXa4etO`, node `1:1701` (thumbnail) / `1:1703` (flattened raster screen).

## Important source limitation

The supplied Community Figma file exposes only one thumbnail page and the UI itself is a flattened raster image, not editable component layers. Therefore exact internal Auto Layout values, font styles, component variants and tokens are not available from Figma. This implementation reconstructs the visible geometry from the raster target while preserving the original composition and avoiding invented controls.

## Numeric layout contract

- Figma thumbnail frame: `1920 × 1080`
- Visible raster node metadata: `1570 × 883`
- Desktop sidebar: ~`282–294px`
- Main conversation width: ~`720–760px`
- Composer width: ~`560–570px`
- Spacing rhythm: `6 / 12 / 18 / 24 / 30 / 36 / 48px`
- No model selector
- No gradient
- No glassmorphism
- No decorative nested cards
- No global shadow system

## Run

```bash
npm install
npm run dev
```

Default Vite URL is typically `http://localhost:5173`.

## Files

- `src/App.tsx` — page structure and interactions
- `src/styles.css` — numeric layout and visual rules
- `src/components/Icons.tsx` — small local line icons, no icon package required
