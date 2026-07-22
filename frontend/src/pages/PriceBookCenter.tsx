import { useEffect, useState } from 'react';
import { apiFetch } from '../utils/api';
import { motion } from 'framer-motion';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

export interface PriceReference {
  id: string;
  item_name: string;
  category?: string;
  brand?: string;
  spec?: string;
  model?: string;
  manufacturer?: string;
  unit_price: number;
  unit: string;
  remark?: string;
}

const emptyFormData = {
  item_name: '',
  brand: '',
  spec: '',
  model: '',
  manufacturer: '',
  unit_price: 0,
  unit: '台',
  remark: ''
};

export function PriceBookCenter() {
  const [items, setItems] = useState<PriceReference[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingItem, setEditingItem] = useState<PriceReference | null>(null);
  const [formData, setFormData] = useState(emptyFormData);


  const fetchItems = async () => {
    setIsLoading(true);
    try {
      const res = await apiFetch(`${API_BASE_URL}/api/v1/business/price-references`);
      if (res.ok) {
        const json = await res.json();
        if (json.code === 200) {
          setItems(json.data);
        }
      }
    } catch (error) {
      console.error('Failed to fetch price references:', error);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchItems();
  }, []);

  const handleDelete = async (id: string) => {
    if (!window.confirm('确认删除此价格项？')) return;
    try {
      const res = await apiFetch(`${API_BASE_URL}/api/v1/business/price-references/${id}`, {
        method: 'DELETE'
      });
      if (res.ok) {
        setItems(prev => prev.filter(item => item.id !== id));
      }
    } catch (error) {
      console.error('Delete failed:', error);
    }
  };

  const handleEdit = (item: PriceReference) => {
    setEditingItem(item);
    setFormData({
      item_name: item.item_name || '',
      brand: item.brand || '',
      spec: item.spec || '',
      model: item.model || '',
      manufacturer: item.manufacturer || '',
      unit_price: item.unit_price || 0,
      unit: item.unit || '台',
      remark: item.remark || ''
    });
    setIsModalOpen(true);
  };

  const handleModalClose = () => {
    setIsModalOpen(false);
    setEditingItem(null);
    setFormData(emptyFormData);
  };

  const handleSave = async () => {
    if (!formData.item_name || formData.unit_price <= 0) {
      alert("请输入设备名称并设置有效的单价");
      return;
    }
    
    try {
      const url = editingItem 
        ? `${API_BASE_URL}/api/v1/business/price-references/${editingItem.id}` 
        : `${API_BASE_URL}/api/v1/business/price-references`;
      const method = editingItem ? 'PUT' : 'POST';
      
      const res = await apiFetch(url, {
        method,
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(formData)
      });

      
      if (res.ok) {
        handleModalClose();
        fetchItems();
      } else {
        alert("保存失败");
      }
    } catch (e) {
      console.error(e);
      alert("保存失败");
    }
  };

  return (
    <motion.div 
      initial={{ opacity: 0, y: 20 }} 
      animate={{ opacity: 1, y: 0 }} 
      transition={{ duration: 0.5 }}
      className="max-w-7xl mx-auto"
    >
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-extrabold text-slate-800 tracking-tight flex items-center">
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-600 to-indigo-600 mr-2">成本与报价中心</span>
            💰
          </h1>
          <p className="text-slate-500 mt-2 font-medium">配置企业内部设备价格参考库，供大模型智能核算使用。</p>
        </div>
        <div className="flex space-x-3">
          <button 
            onClick={() => { setEditingItem(null); setFormData(emptyFormData); setIsModalOpen(true); }}
            className="flex items-center px-5 py-3 bg-gradient-to-r from-blue-600 to-indigo-600 text-white font-bold rounded-xl shadow-lg hover:shadow-indigo-500/30 hover:-translate-y-0.5 transition-all"
          >
            <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4"></path></svg>
            添加指导单价
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="py-20 flex justify-center items-center">
          <svg className="animate-spin h-8 w-8 text-indigo-500" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
        </div>
      ) : items.length === 0 ? (
        <div className="bg-white/60 backdrop-blur-md rounded-3xl border border-dashed border-slate-300 p-20 flex flex-col items-center justify-center text-center">
          <div className="w-20 h-20 bg-slate-100 rounded-full flex items-center justify-center text-4xl mb-4">📭</div>
          <h3 className="text-xl font-bold text-slate-700 mb-2">价格库空空如也</h3>
          <p className="text-slate-500 max-w-md">点击右上角“添加指导单价”录入设备底价。大模型会自动在解析标书时为您测算总成本。</p>
        </div>
      ) : (
        <div className="bg-white rounded-3xl shadow-sm border border-slate-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200 text-slate-500 text-sm">
                  <th className="py-4 px-6 font-bold whitespace-nowrap">设备/物品名称</th>
                  <th className="py-4 px-6 font-bold whitespace-nowrap">品牌</th>
                  <th className="py-4 px-6 font-bold whitespace-nowrap">规格</th>
                  <th className="py-4 px-6 font-bold whitespace-nowrap">型号</th>
                  <th className="py-4 px-6 font-bold whitespace-nowrap">生产厂商</th>
                  <th className="py-4 px-6 font-bold whitespace-nowrap">指导单价 (RMB)</th>
                  <th className="py-4 px-6 font-bold whitespace-nowrap">单位</th>
                  <th className="py-4 px-6 font-bold whitespace-nowrap">备注</th>
                  <th className="py-4 px-6 font-bold text-right whitespace-nowrap">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {items.map(item => (
                  <tr key={item.id} className="hover:bg-slate-50 transition-colors">
                    <td className="py-4 px-6">
                      <p className="font-bold text-slate-800">{item.item_name}</p>
                    </td>
                    <td className="py-4 px-6">
                      <span className="text-slate-700 font-medium">{item.brand || '-'}</span>
                    </td>
                    <td className="py-4 px-6">
                      <span className="text-slate-600 font-medium text-sm">{item.spec || '-'}</span>
                    </td>
                    <td className="py-4 px-6">
                      <span className="text-slate-600 font-medium text-sm">{item.model || '-'}</span>
                    </td>
                    <td className="py-4 px-6">
                      <span className="text-slate-700 font-medium">{item.manufacturer || '-'}</span>
                    </td>
                    <td className="py-4 px-6">
                      <span className="font-bold text-blue-600">¥{item.unit_price.toLocaleString()}</span>
                    </td>
                    <td className="py-4 px-6">
                      <span className="text-slate-700 font-medium">{item.unit}</span>
                    </td>
                    <td className="py-4 px-6 max-w-xs relative">
                      {item.remark ? (
                        <div className="relative group inline-block max-w-full">
                          <p className="text-slate-600 text-sm truncate cursor-pointer hover:text-blue-600 transition-colors">
                            {item.remark}
                          </p>
                          {/* 鼠标悬停自动浮现完整备注卡片 */}
                          <div className="absolute left-0 bottom-full mb-2 hidden group-hover:block z-[99] w-72 p-3.5 bg-slate-900/95 backdrop-blur-md text-white text-xs rounded-2xl shadow-2xl border border-slate-700/50 pointer-events-none break-words transition-all">
                            <div className="flex items-center space-x-1.5 font-bold text-blue-400 mb-1">
                              <span>📝</span>
                              <span>详细备注说明</span>
                            </div>
                            <p className="text-slate-200 leading-relaxed font-normal">
                              {item.remark}
                            </p>
                            <div className="absolute top-full left-5 -mt-px border-4 border-transparent border-t-slate-900/95" />
                          </div>
                        </div>
                      ) : (
                        <span className="text-slate-400 text-sm">-</span>
                      )}
                    </td>


                    <td className="py-4 px-6">
                      <div className="flex items-center justify-end space-x-2">
                        <button onClick={() => handleEdit(item)} className="p-2 text-blue-500 bg-blue-50 hover:bg-blue-100 rounded-lg transition-colors" title="编辑">
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path></svg>
                        </button>
                        <button onClick={() => handleDelete(item.id)} className="p-2 text-rose-500 bg-rose-50 hover:bg-rose-100 rounded-lg transition-colors" title="删除">
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm">
          <motion.div 
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            className="w-full max-w-xl bg-white rounded-3xl shadow-2xl overflow-hidden"
          >
            <div className="flex items-center justify-between px-6 py-5 border-b border-slate-100">
              <h3 className="text-xl font-bold text-slate-800 flex items-center">
                <span className="text-2xl mr-2">{editingItem ? '✏️' : '✨'}</span>
                {editingItem ? '编辑设备价格项' : '添加新设备价格'}
              </h3>
              <button onClick={handleModalClose} className="text-slate-400 hover:text-slate-600 transition-colors">
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12"></path></svg>
              </button>
            </div>
            
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-bold text-slate-700 mb-1">设备/物品名称 <span className="text-rose-500">*</span></label>
                <input 
                  type="text" 
                  value={formData.item_name}
                  onChange={e => setFormData({...formData, item_name: e.target.value})}
                  className="w-full bg-slate-50 border border-slate-200 rounded-xl px-4 py-3 text-slate-800 outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all font-medium"
                  placeholder="例如: 核心交换机"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div>
                  <label className="block text-sm font-bold text-slate-700 mb-1">品牌</label>
                  <input 
                    type="text" 
                    value={formData.brand}
                    onChange={e => setFormData({...formData, brand: e.target.value})}
                    className="w-full bg-slate-50 border border-slate-200 rounded-xl px-4 py-3 text-slate-800 outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all font-medium"
                    placeholder="例如: 华为"
                  />
                </div>
                <div>
                  <label className="block text-sm font-bold text-slate-700 mb-1">规格</label>
                  <input 
                    type="text" 
                    value={formData.spec}
                    onChange={e => setFormData({...formData, spec: e.target.value})}
                    className="w-full bg-slate-50 border border-slate-200 rounded-xl px-4 py-3 text-slate-800 outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all font-medium"
                    placeholder="例如: 24口千兆"
                  />
                </div>
                <div>
                  <label className="block text-sm font-bold text-slate-700 mb-1">型号</label>
                  <input 
                    type="text" 
                    value={formData.model}
                    onChange={e => setFormData({...formData, model: e.target.value})}
                    className="w-full bg-slate-50 border border-slate-200 rounded-xl px-4 py-3 text-slate-800 outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all font-medium"
                    placeholder="例如: S5735-S"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-bold text-slate-700 mb-1">生产厂商</label>
                <input 
                  type="text" 
                  value={formData.manufacturer}
                  onChange={e => setFormData({...formData, manufacturer: e.target.value})}
                  className="w-full bg-slate-50 border border-slate-200 rounded-xl px-4 py-3 text-slate-800 outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all font-medium"
                  placeholder="例如: 华为技术有限公司"
                />
              </div>

              <div className="flex space-x-4">
                <div className="flex-1">
                  <label className="block text-sm font-bold text-slate-700 mb-1">指导单价 (元) <span className="text-rose-500">*</span></label>
                  <input 
                    type="number" 
                    value={formData.unit_price}
                    onChange={e => setFormData({...formData, unit_price: Number(e.target.value)})}
                    className="w-full bg-slate-50 border border-slate-200 rounded-xl px-4 py-3 text-slate-800 outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all font-medium"
                    placeholder="0.00"
                  />
                </div>
                <div className="w-32">
                  <label className="block text-sm font-bold text-slate-700 mb-1">单位</label>
                  <input 
                    type="text" 
                    value={formData.unit}
                    onChange={e => setFormData({...formData, unit: e.target.value})}
                    className="w-full bg-slate-50 border border-slate-200 rounded-xl px-4 py-3 text-slate-800 outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all font-medium text-center"
                    placeholder="台"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-bold text-slate-700 mb-1">备注</label>
                <textarea 
                  rows={2}
                  value={formData.remark}
                  onChange={e => setFormData({...formData, remark: e.target.value})}
                  className="w-full bg-slate-50 border border-slate-200 rounded-xl px-4 py-2.5 text-slate-800 outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all font-medium resize-none"
                  placeholder="可输入额外备注说明..."
                />
              </div>
            </div>
            
            <div className="px-6 py-5 bg-slate-50 flex justify-end space-x-3">
              <button 
                onClick={handleModalClose}
                className="px-6 py-2.5 rounded-xl font-bold text-slate-600 hover:bg-slate-200 transition-colors"
              >
                取消
              </button>
              <button 
                onClick={handleSave}
                className="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-xl shadow-lg shadow-blue-500/30 transition-all"
              >
                保存配置
              </button>
            </div>
          </motion.div>
        </div>
      )}
    </motion.div>
  );
}
