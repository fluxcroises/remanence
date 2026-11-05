; Installateur de Remanence (Inno Setup 6), fabriqué par Construire.bat après Remanence.exe :
;   ISCC.exe /DVersion=1.0.0 Remanence.iss
; Résultat : dist\Remanence-<version>-installation.exe.
;
; Installation pour l'utilisateur, sans droits d'administrateur, dans
; %LOCALAPPDATA%\Programs\Remanence. FFglitch n'est pas inclus : Remanence le télécharge au
; premier lancement, dans le dossier « outils » à côté de Remanence.exe (vidé à la
; désinstallation). Les projets, les réglages et le journal restent après la désinstallation.

#ifndef Version
  #define Version "1.0.0"
#endif

[Setup]
; Identifiant fixe : une nouvelle version remplace l'ancienne au lieu de s'installer à côté.
AppId={{F0F6C70C-6D7E-48AC-AFDE-D030DD36D9D4}
AppName=Remanence
AppVersion={#Version}
AppVerName=Remanence {#Version}
AppPublisher=Flux Croisés
AppCopyright=© 2026 Flux Croisés
VersionInfoVersion={#Version}
VersionInfoCompany=Flux Croisés
VersionInfoDescription=Installation de Remanence
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\Remanence
DefaultGroupName=Remanence
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=dist
OutputBaseFilename=Remanence-{#Version}-installation
SetupIconFile=remanence\ressources\remanence.ico
UninstallDisplayIcon={app}\Remanence.exe
UninstallDisplayName=Remanence
WizardStyle=modern
WizardImageFile=build\installateur\panneau_164.bmp,build\installateur\panneau_246.bmp,build\installateur\panneau_328.bmp
WizardSmallImageFile=build\installateur\icone_55.bmp,build\installateur\icone_83.bmp,build\installateur\icone_110.bmp
Compression=lzma2/max
SolidCompression=yes
ChangesAssociations=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "francais"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "bureau"; Description: "Raccourci sur le bureau"; Flags: unchecked

[Files]
; Le dossier construit, sans FFglitch (téléchargé au premier lancement).
Source: "dist\Remanence\*"; DestDir: "{app}"; Excludes: "\outils"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Remanence"; Filename: "{app}\Remanence.exe"
Name: "{autodesktop}\Remanence"; Filename: "{app}\Remanence.exe"; Tasks: bureau

[Registry]
; Fichiers .remanence : double-clic pour ouvrir le projet, icône de Remanence.
Root: HKA; Subkey: "Software\Classes\.remanence"; ValueType: string; ValueName: ""; ValueData: "Remanence.Projet"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Remanence.Projet"; ValueType: string; ValueName: ""; ValueData: "Projet Remanence"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Remanence.Projet\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\Remanence.exe,0"
Root: HKA; Subkey: "Software\Classes\Remanence.Projet\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Remanence.exe"" ""%1"""

[Run]
Filename: "{app}\Remanence.exe"; Description: "Lancer Remanence"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; FFglitch, téléchargé par Remanence après l'installation.
Type: filesandordirs; Name: "{app}\outils"
