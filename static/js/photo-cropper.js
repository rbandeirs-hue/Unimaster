/**
 * Photo Cropper - permite selecionar área e zoom ao escolher arquivo de foto.
 * Uso: initPhotoCrop(fileInputEl, { fotoInput, miniatura, placeholder })
 * Requer: Cropper.js (https://cdnjs.cloudflare.com/ajax/libs/cropperjs/1.6.1/cropper.min.js)
 */
(function() {
  'use strict';

  var cropModal = null;
  var cropImg = null;
  var cropperInstance = null;
  var pendingCallback = null;
  var currentFileInput = null;

  function getOrCreateModal() {
    if (cropModal) return cropModal;
    cropModal = document.createElement('div');
    cropModal.className = 'photo-crop-modal';
    cropModal.id = 'photoCropModal';
    cropModal.innerHTML = '<div class="photo-crop-container">' +
      '<h6><i class="bi bi-crop me-1"></i> Ajuste a área e o zoom da foto</h6>' +
      '<div class="img-container">' +
        '<img id="photoCropImg" src="" alt="">' +
      '</div>' +
      '<div class="crop-btns">' +
        '<button type="button" class="btn btn-success" id="photoCropConfirm"><i class="bi bi-check-lg me-1"></i> Usar foto</button>' +
        '<button type="button" class="btn btn-outline-light" id="photoCropCancel"><i class="bi bi-x-lg me-1"></i> Cancelar</button>' +
      '</div></div>';
    document.body.appendChild(cropModal);

    cropImg = document.getElementById('photoCropImg');

    document.getElementById('photoCropConfirm').addEventListener('click', function() {
      if (cropperInstance && pendingCallback) {
        var canvas = cropperInstance.getCroppedCanvas({
          width: 400,
          height: 400,
          imageSmoothingEnabled: true,
          imageSmoothingQuality: 'high',
          fillColor: '#fff'
        });
        if (canvas) {
          var dataUrl = canvas.toDataURL('image/png');
          pendingCallback(dataUrl);
        }
      }
      closeCropModal();
    });

    document.getElementById('photoCropCancel').addEventListener('click', closeCropModal);
    cropModal.addEventListener('click', function(e) {
      if (e.target === cropModal) closeCropModal();
    });

    return cropModal;
  }

  function closeCropModal() {
    if (cropperInstance) {
      cropperInstance.destroy();
      cropperInstance = null;
    }
    pendingCallback = null;
    if (currentFileInput) currentFileInput.value = '';
    currentFileInput = null;
    if (cropModal) {
      cropModal.classList.remove('show');
      cropModal.style.display = 'none';
    }
    if (cropImg) cropImg.src = '';
  }

  window.initPhotoCrop = function(fileInput, options) {
    if (!fileInput) return;
    var fotoInput = options && options.fotoInput ? (typeof options.fotoInput === 'string' ? document.getElementById(options.fotoInput) : options.fotoInput) : null;
    var miniatura = options && options.miniatura ? (typeof options.miniatura === 'string' ? document.getElementById(options.miniatura) : options.miniatura) : null;
    var placeholder = options && options.placeholder ? (typeof options.placeholder === 'string' ? document.getElementById(options.placeholder) : options.placeholder) : null;
    var aspectRatio = options && options.aspectRatio !== undefined ? options.aspectRatio : 1;

    fileInput.addEventListener('change', function() {
      var file = this.files[0];
      if (!file || !file.type || file.type.indexOf('image') !== 0) return;

      var reader = new FileReader();
      reader.onload = function(e) {
        var modal = getOrCreateModal();
        cropImg.src = e.target.result;
        modal.style.display = 'flex';
        modal.classList.add('show');

        currentFileInput = fileInput;
        pendingCallback = function(dataUrl) {
          if (fotoInput) fotoInput.value = dataUrl;
          if (miniatura) {
            miniatura.src = dataUrl;
            miniatura.classList.remove('d-none');
          }
          if (placeholder) placeholder.classList.add('d-none');
          fileInput.value = '';
        };

        setTimeout(function() {
          if (cropperInstance) cropperInstance.destroy();
          cropperInstance = new Cropper(cropImg, {
            aspectRatio: aspectRatio,
            viewMode: 1,
            dragMode: 'move',
            autoCropArea: 0.8,
            restore: false,
            guides: true,
            center: true,
            highlight: false,
            cropBoxMovable: true,
            cropBoxResizable: true,
            toggleDragModeOnDblclick: false
          });
        }, 50);
      };
      reader.readAsDataURL(file);
    });
  };

  window.initPhotoCropBySelectors = function(selectors) {
    selectors.forEach(function(s) {
      var fileInput = typeof s.file === 'string' ? document.querySelector(s.file) : s.file;
      if (fileInput) initPhotoCrop(fileInput, s);
    });
  };
})();
