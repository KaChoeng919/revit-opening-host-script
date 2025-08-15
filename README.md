# Revit Opening Host Script

## 描述 (Description)
這個Python腳本用於Autodesk Revit，專門處理"GEN-CSC-Opening-Rectangular"族的開口元素，將無宿主的開口轉換為宿主於樓板（Floor）的開口。腳本會：
- 收集開口、樓板和Grid。
- 為每個開口創建臨時副本檢查交疊樓板。
- 投影到最近水平面，創建新宿主實例。
- 基於Grid距離檢查決定是否互換寬高。
- 記錄詳細日志。

已修復問題：
- 邊界重疊：臨時縮小尺寸找樓板，後還原。
- 方向旋轉：使用原元素方向投影到樓板面。
- 其他bug：如XYZ減法錯誤。

This Python script for Autodesk Revit processes rectangular opening elements from the "GEN-CSC-Opening-Rectangular" family, converting unhosted openings to floor-hosted ones. It collects openings, floors, and grids, checks for overlaps, projects to the nearest horizontal face, creates new hosted instances, and swaps width/height based on grid distance consistency. Detailed logging is included.

Fixed issues: Boundary overlap (temporary shrink and restore), direction rotation (project original direction), and bugs like XYZ subtraction.

## 依賴 (Dependencies)
- Revit API (運行於Revit環境，如Dynamo或PyRevit)。
- IronPython (Revit預設)。
- 無需額外安裝。

## 使用方式 (Usage)
1. 在Revit中載入腳本（e.g., via Dynamo）。
2. 確保模型有Grid "13" 和 "AA"（或修改代碼）。
3. 運行腳本：輸出新實例列表和日志檔案（D:\Users\User\Desktop\test\error_log.txt）。
4. 檢查日志以驗證成功/失敗。

Run in Revit (e.g., Dynamo). Ensure grids "13" and "AA" exist. Output: new instances and log file.

## 注意事項 (Notes)
- 單位：英尺內部，毫米顯示。
- 容差：DIST_TOL_MM=20mm, SHRINK_MM=50mm（可調整）。
- 日志路徑硬編碼，可修改。

## 貢獻 (Contributing)
歡迎PR。報告問題請附日志。

Welcome PRs. Report issues with logs.

## 許可證 (License)
MIT License
