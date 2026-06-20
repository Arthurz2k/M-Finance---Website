document.addEventListener('DOMContentLoaded', () => {
    const fileInput = document.getElementById('file-input');
    const tableBody = document.getElementById('recent-uploads-list');

    // Quando um arquivo for selecionado pelo clique
    if (fileInput) {
        fileInput.addEventListener('change', function() {
            if (this.files.length > 0) {
                uploadFile(this.files[0]);
            }
        });
    }

    function uploadFile(file) {
        const formData = new FormData();
        formData.append('file', file);

        // Cria uma linha temporária de "Processando"
        const rowId = 'row-' + Date.now();
        const tr = document.createElement('tr');
        tr.id = rowId;
        tr.innerHTML = `
            <td>${file.name}</td>
            <td>Imagem</td>
            <td>Lendo...</td>
            <td><span class="status processing">Processando...</span></td>
        `;
        tableBody.prepend(tr);

        // Envia para o Python
        fetch('/upload', {
            method: 'POST',
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            const row = document.getElementById(rowId);
            if (data.error) {
                row.innerHTML = `
                    <td>${file.name}</td>
                    <td>Imagem</td>
                    <td>--</td>
                    <td><span class="status error">${data.error}</span></td>
                `;
            } else {
                row.innerHTML = `
                    <td>${file.name}</td>
                    <td>${data.tipo}</td>
                    <td><strong>R$ ${data.valor}</strong></td>
                    <td><span class="status success">${data.message}</span></td>
                `;
            }
        })
        .catch(error => console.error('Erro no upload:', error));
    }
});