Unicode true
!include "MUI2.nsh"
!include "x64.nsh"
!include "WinVer.nsh"

!ifndef PROJECT_ROOT
  !define PROJECT_ROOT "${__FILEDIR__}\.."
!endif
!define APP_NAME "商品资料台"
!define APP_VERSION "1.0.2"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\ProductDesk"

Name "${APP_NAME}"
Caption "${APP_NAME} 安装向导"
OutFile "${PROJECT_ROOT}\dist\商品资料台-${APP_VERSION}-安装程序.exe"
InstallDir "$LOCALAPPDATA\Programs\ProductDesk"
InstallDirRegKey HKCU "Software\ProductDesk" "InstallLocation"
RequestExecutionLevel user
ManifestDPIAware true
SetCompressor /SOLID lzma
SetFont "Microsoft YaHei" 9
ShowInstDetails show
ShowUninstDetails show
VIProductVersion "1.0.2.0"
VIAddVersionKey /LANG=2052 "ProductName" "${APP_NAME}"
VIAddVersionKey /LANG=2052 "FileDescription" "${APP_NAME} 中文安装程序"
VIAddVersionKey /LANG=2052 "FileVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=2052 "ProductVersion" "${APP_VERSION}"

!define MUI_ICON "${PROJECT_ROOT}\assets\app-icon.ico"
!define MUI_UNICON "${PROJECT_ROOT}\assets\app-icon.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "欢迎安装${APP_NAME}"
!define MUI_WELCOMEPAGE_TEXT "本向导将安装${APP_NAME} ${APP_VERSION}。$\r$\n$\r$\n用于整理商品 Excel、汇总品牌及维护商品备注。$\r$\n$\r$\n安装后可直接使用，无需另行安装 Python。$\r$\n$\r$\n请先关闭已打开的商品资料台，然后点击“下一步”。"
!define MUI_FINISHPAGE_TITLE "${APP_NAME}安装完成"
!define MUI_FINISHPAGE_TEXT "${APP_NAME}已安装到您的电脑。$\r$\n$\r$\n可以从开始菜单或桌面快捷方式打开。备注及设置保存在当前用户的数据目录，卸载时会保留。"
!define MUI_FINISHPAGE_RUN "$INSTDIR\ProductDesk.exe"
!define MUI_FINISHPAGE_RUN_TEXT "启动${APP_NAME}"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH
!insertmacro MUI_LANGUAGE "SimpChinese"

Function .onInit
  SetShellVarContext current
  ${IfNot} ${RunningX64}
    MessageBox MB_OK|MB_ICONSTOP "此安装程序需要 64 位 Windows 10 或更高版本。"
    Abort
  ${EndIf}
  ${IfNot} ${AtLeastWin10}
    MessageBox MB_OK|MB_ICONSTOP "此安装程序需要 Windows 10 或更高版本。"
    Abort
  ${EndIf}
  SetRegView 64
FunctionEnd

Section "商品资料台（必选）" AppSection
  SectionIn RO
  SetShellVarContext current
  SetRegView 64
  SetOutPath "$INSTDIR"
  File /r "${PROJECT_ROOT}\dist\ProductDesk\*.*"
  WriteUninstaller "$INSTDIR\uninstall.exe"
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\ProductDesk.exe"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\卸载${APP_NAME}.lnk" "$INSTDIR\uninstall.exe"
  WriteRegStr HKCU "Software\ProductDesk" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\ProductDesk.exe"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "UninstallString" '$\"$INSTDIR\uninstall.exe$\"'
  WriteRegStr HKCU "${UNINSTALL_KEY}" "QuietUninstallString" '$\"$INSTDIR\uninstall.exe$\" /S'
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair" 1
SectionEnd

Section "创建桌面快捷方式" DesktopSection
  CreateShortcut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\ProductDesk.exe"
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${AppSection} "安装商品资料台及全部运行组件。"
  !insertmacro MUI_DESCRIPTION_TEXT ${DesktopSection} "在当前用户的桌面创建快捷方式。"
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Section "Uninstall"
  SetShellVarContext current
  SetRegView 64
  !include "${PROJECT_ROOT}\build\uninstall-files.nsh"
  Delete "$INSTDIR\uninstall.exe"
  RMDir "$INSTDIR"
  Delete "$DESKTOP\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\卸载${APP_NAME}.lnk"
  RMDir "$SMPROGRAMS\${APP_NAME}"
  DeleteRegKey HKCU "${UNINSTALL_KEY}"
  DeleteRegKey HKCU "Software\ProductDesk"
SectionEnd
