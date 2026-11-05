; Installateur de Remanence (Inno Setup 6), fabriqué par Construire.bat après Remanence.exe :
;   ISCC.exe /DVersion=1.0.0 Remanence.iss
; Résultat : dist\Remanence-<version>-installation.exe.
;
; Par défaut, pour tous les comptes, dans C:\Program Files\Flux Croisés\Remanence (Windows
; demande l'autorisation d'administrateur), comme Vegas Pro ou DaVinci Resolve. Au départ,
; l'assistant propose aussi « Pour moi seulement » : sans autorisation, dans
; %LOCALAPPDATA%\Programs\Flux Croisés\Remanence (choix de Lewis, 5 novembre 2026).
; FFglitch n'est pas inclus : Remanence le télécharge au premier lancement, à côté de
; Remanence.exe si ce dossier est inscriptible, sinon dans %LOCALAPPDATA%\Remanence\outils ;
; les deux sont vidés à la désinstallation. Les projets, les réglages et le journal restent.

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
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\Flux Croisés\Remanence
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
Root: HKA; Subkey: "Software\Classes\.remanence"; ValueType: string; ValueName: ""; ValueData: "Remanence.Projet"; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKA; Subkey: "Software\Classes\Remanence.Projet"; ValueType: string; ValueName: ""; ValueData: "Projet Remanence"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Remanence.Projet\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\Remanence.exe,0"
Root: HKA; Subkey: "Software\Classes\Remanence.Projet\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Remanence.exe"" ""%1"""

[Run]
; Lancé comme l'utilisateur et non comme administrateur (réglages et journal à leur place).
Filename: "{app}\Remanence.exe"; Description: "Lancer Remanence"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallDelete]
; FFglitch, téléchargé par Remanence après l'installation (à côté du programme, ou dans le
; dossier local du compte qui désinstalle quand Program Files était protégé).
Type: filesandordirs; Name: "{app}\outils"
Type: filesandordirs; Name: "{localappdata}\Remanence\outils"
; Le dossier de l'éditeur, s'il ne contient plus rien (il peut héberger d'autres logiciels de
; Flux Croisés, comme Afterdusk).
Type: dirifempty; Name: "{autopf}\Flux Croisés"
