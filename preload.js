const { contextBridge, ipcRenderer, webUtils } = require('electron');

contextBridge.exposeInMainWorld('psyop', {
  isElectron: true,
  openVideoDialog: () => ipcRenderer.invoke('dialog:openVideo'),
  probePath: (filePath) => ipcRenderer.invoke('video:probePath', filePath),
  getPathForFile: (file) => {
    if (webUtils && typeof webUtils.getPathForFile === 'function') {
      return webUtils.getPathForFile(file);
    }
    return file.path || '';
  },
  generatePlan: (payload) => ipcRenderer.invoke('video:generatePlan', payload),
  renderVideo: (payload) => ipcRenderer.invoke('video:render', payload),
  revealInFolder: (filePath) => ipcRenderer.invoke('shell:revealFile', filePath),
  openExternalPlayer: (filePath) => ipcRenderer.invoke('shell:openFile', filePath),
  expandForResult: () => ipcRenderer.invoke('window:expandForResult'),
  onRenderProgress: (callback) => {
    const listener = (_event, data) => callback(data);
    ipcRenderer.on('render:progress', listener);
    return () => ipcRenderer.removeListener('render:progress', listener);
  }
});
