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

<script>
async function processarUploads(arquivos) {
    if (arquivos.length === 0) return;

    // Se você tiver o campo de tag na tela, ele pega o valor, se não, envia 'Outros'
    const tagElement = document.getElementById('tag');
    const tag = tagElement ? tagElement.value : 'Outros';

    let sucesso = 0;
    let falha = 0;

    // Aviso de início (você pode substituir pelo seu modal de carregamento)
    alert(`Iniciando o processamento de ${arquivos.length} arquivo(s)... Aguarde.`);

    // Faz o loop enviando um arquivo por vez
    for (let i = 0; i < arquivos.length; i++) {
        let formData = new FormData();
        formData.append('file', arquivos[i]);
        formData.append('tag', tag);

        try {
            let response = await fetch('/upload', { method: 'POST', body: formData });
            let result = await response.json();
            
            if (response.ok && !result.error) {
                sucesso++;
            } else {
                falha++;
                console.error("Erro no arquivo:", arquivos[i].name, result.error);
            }
        } catch (err) {
            falha++;
            console.error("Falha na conexão do arquivo:", arquivos[i].name);
        }
    }

    alert(`Processamento concluído!\n✅ Sucessos: ${sucesso}\n❌ Falhas ou Duplicados: ${falha}`);
    window.location.reload(); // Recarrega a página para mostrar os novos dados
}
</script>